"""Bronze → Silver: parse raw envelopes into typed, deduplicated tables.

  python -m smartcity.pipeline.bronze_to_silver

Silver tables (parquet):
  silver/stations          one row per station (latest dimension snapshot)
  silver/station_status    one row per (station, last_reported) telemetry event
  silver/air_quality       one row per (zone, observed_at) model observation
  silver/traffic_readings  one row per (road sensor, hour) flow/occupancy event
  silver/transactions      one row per cleaned DVF property sale
  silver/amenities         one row per OSM point of interest
"""
from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window

from smartcity.config import BRONZE_DIR, SILVER_DIR
from smartcity.pipeline.session import get_spark


def _read_feed(spark: SparkSession, feed: str) -> DataFrame | None:
    path = BRONZE_DIR / f"feed={feed}"
    if not path.exists():
        print(f"[skip] no bronze data for {feed}")
        return None
    return spark.read.option("multiLine", "true").json(str(path / "*" / "*.json"))


def build_stations(spark: SparkSession) -> None:
    raw = _read_feed(spark, "gbfs_station_information")
    if raw is None:
        return
    df = (
        raw.select("polled_at", F.explode("payload.data.stations").alias("s"))
        .select(
            F.col("s.station_id").cast("string").alias("station_id"),
            F.col("s.name").alias("name"),
            F.col("s.lat").cast("double").alias("lat"),
            F.col("s.lon").cast("double").alias("lon"),
            F.col("s.capacity").cast("int").alias("capacity"),
            F.to_timestamp("polled_at").alias("polled_at"),
        )
        .where(F.col("station_id").isNotNull() & F.col("lat").isNotNull() & F.col("lon").isNotNull())
    )
    # keep only the latest snapshot per station (slowly-changing dimension)
    w = Window.partitionBy("station_id").orderBy(F.desc("polled_at"))
    latest = df.withColumn("rn", F.row_number().over(w)).where("rn = 1").drop("rn")
    latest.write.mode("overwrite").parquet(str(SILVER_DIR / "stations"))
    print(f"silver/stations: {latest.count()} stations")


def _bike_type_col(status_struct_type, kind: str):
    """Vélib' reports num_bikes_available_types as an array of single-key
    objects ([{mechanical: n}, {ebike: m}]); coalesce across elements."""
    return F.coalesce(
        F.col("s.num_bikes_available_types")[0][kind],
        F.col("s.num_bikes_available_types")[1][kind],
    )


def build_station_status(spark: SparkSession) -> None:
    raw = _read_feed(spark, "gbfs_station_status")
    if raw is None:
        return
    df = raw.select("polled_at", F.explode("payload.data.stations").alias("s")).select(
        F.col("s.station_id").cast("string").alias("station_id"),
        F.col("s.num_bikes_available").cast("int").alias("bikes_available"),
        _bike_type_col(raw, "mechanical").cast("int").alias("bikes_mechanical"),
        _bike_type_col(raw, "ebike").cast("int").alias("bikes_ebike"),
        F.col("s.num_docks_available").cast("int").alias("docks_available"),
        (F.col("s.is_renting").cast("int") == 1).alias("is_renting"),
        (F.col("s.is_installed").cast("int") == 1).alias("is_installed"),
        F.to_timestamp(F.from_unixtime("s.last_reported")).alias("reported_at"),
        F.to_timestamp("polled_at").alias("polled_at"),
    )
    # dedup: a station re-polled before it re-reports is the same telemetry event
    w = Window.partitionBy("station_id", "reported_at").orderBy(F.desc("polled_at"))
    events = (
        df.where(F.col("station_id").isNotNull() & F.col("reported_at").isNotNull())
        .withColumn("rn", F.row_number().over(w))
        .where("rn = 1")
        .drop("rn")
    )
    events.write.mode("overwrite").parquet(str(SILVER_DIR / "station_status"))
    print(f"silver/station_status: {events.count()} telemetry events")


def build_air_quality(spark: SparkSession) -> None:
    raw = _read_feed(spark, "air_quality")
    if raw is None:
        return
    df = raw.select("polled_at", F.explode("payload").alias("p")).select(
        F.col("p.zone").alias("zone"),
        F.to_timestamp("p.current.time").alias("observed_at"),
        F.col("p.current.pm10").cast("double").alias("pm10"),
        F.col("p.current.pm2_5").cast("double").alias("pm2_5"),
        F.col("p.current.nitrogen_dioxide").cast("double").alias("no2"),
        F.col("p.current.ozone").cast("double").alias("o3"),
        F.col("p.current.european_aqi").cast("double").alias("eaqi"),
        F.to_timestamp("polled_at").alias("polled_at"),
    )
    w = Window.partitionBy("zone", "observed_at").orderBy(F.desc("polled_at"))
    obs = (
        df.where(F.col("zone").isNotNull() & F.col("observed_at").isNotNull())
        .withColumn("rn", F.row_number().over(w))
        .where("rn = 1")
        .drop("rn")
    )
    obs.write.mode("overwrite").parquet(str(SILVER_DIR / "air_quality"))
    print(f"silver/air_quality: {obs.count()} observations")


def build_traffic(spark: SparkSession) -> None:
    path = BRONZE_DIR / "feed=traffic"
    if not path.exists():
        print("[skip] no bronze data for traffic")
        return
    raw = (
        spark.read.option("header", "true").option("sep", ";")
        .csv(str(path / "*" / "*.csv"))
    )
    raw = raw.toDF(*[c.replace("﻿", "") for c in raw.columns])  # strip BOM
    geo = F.split(F.col("geo_point_2d"), ",\\s*")
    df = raw.select(
        F.col("iu_ac").cast("string").alias("sensor_id"),
        F.col("libelle").alias("name"),
        F.to_timestamp("t_1h").alias("observed_at"),
        F.col("q").cast("double").alias("flow_vph"),
        F.col("k").cast("double").alias("occupancy_pct"),
        F.col("etat_trafic").alias("state"),
        geo.getItem(0).cast("double").alias("lat"),
        geo.getItem(1).cast("double").alias("lon"),
    ).where(
        F.col("sensor_id").isNotNull() & F.col("observed_at").isNotNull()
        & F.col("flow_vph").isNotNull() & F.col("lat").isNotNull()
    )
    # overlapping poll windows re-deliver the same (sensor, hour) rows
    events = df.dropDuplicates(["sensor_id", "observed_at"])
    events.write.mode("overwrite").parquet(str(SILVER_DIR / "traffic_readings"))
    print(f"silver/traffic_readings: {events.count()} readings")


def build_transactions(spark: SparkSession) -> None:
    path = BRONZE_DIR / "feed=dvf"
    if not path.exists():
        print("[skip] no bronze data for dvf")
        return
    raw = spark.read.option("header", "true").csv(str(path / "*" / "*.csv.gz"))
    df = raw.select(
        F.col("id_mutation"),
        F.to_date("date_mutation").alias("sold_on"),
        F.col("nature_mutation"),
        F.col("valeur_fonciere").cast("double").alias("price_eur"),
        F.col("type_local").alias("property_type"),
        F.col("surface_reelle_bati").cast("double").alias("surface_m2"),
        F.col("nombre_pieces_principales").cast("int").alias("rooms"),
        F.col("code_postal").alias("postal_code"),
        F.col("id_parcelle"),
        F.col("longitude").cast("double").alias("lon"),
        F.col("latitude").cast("double").alias("lat"),
    )
    clean = (
        df.where(
            (F.col("nature_mutation") == "Vente")
            & F.col("property_type").isin("Appartement", "Maison")
            & F.col("lat").isNotNull() & F.col("lon").isNotNull()
            & (F.col("surface_m2") >= 9) & (F.col("price_eur") >= 10_000)
        )
        .withColumn("price_m2", F.round(F.col("price_eur") / F.col("surface_m2"), 0))
        # multi-lot mutations produce absurd per-row €/m²; keep the plausible band
        .where(F.col("price_m2").between(2_000, 40_000))
        .withColumn("year", F.year("sold_on"))
        .dropDuplicates(["id_mutation", "id_parcelle", "property_type", "surface_m2", "price_eur"])
        .drop("nature_mutation")
    )
    clean.write.mode("overwrite").parquet(str(SILVER_DIR / "transactions"))
    print(f"silver/transactions: {clean.count()} sales")


def build_amenities(spark: SparkSession) -> None:
    raw = _read_feed(spark, "amenities")
    if raw is None:
        return
    df = raw.select(
        "polled_at",
        F.col("payload.kind").alias("kind"),
        F.explode("payload.features").alias("a"),
    ).select(
        F.col("a.osm_id").alias("osm_id"),
        "kind",
        F.col("a.name").alias("name"),
        F.col("a.lat").cast("double").alias("lat"),
        F.col("a.lon").cast("double").alias("lon"),
        F.to_timestamp("polled_at").alias("polled_at"),
    )
    w = Window.partitionBy("osm_id").orderBy(F.desc("polled_at"))
    latest = df.withColumn("rn", F.row_number().over(w)).where("rn = 1").drop("rn", "polled_at")
    latest.write.mode("overwrite").parquet(str(SILVER_DIR / "amenities"))
    print(f"silver/amenities: {latest.count()} POIs")


def main() -> None:
    spark = get_spark("bronze_to_silver")
    spark.sparkContext.setLogLevel("WARN")
    build_stations(spark)
    build_station_status(spark)
    build_air_quality(spark)
    build_traffic(spark)
    build_transactions(spark)
    build_amenities(spark)
    spark.stop()


if __name__ == "__main__":
    main()
