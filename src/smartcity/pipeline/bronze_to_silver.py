"""Bronze → Silver: parse raw envelopes into typed, deduplicated tables.

  python -m smartcity.pipeline.bronze_to_silver

Silver tables (parquet):
  silver/stations        one row per station (latest dimension snapshot)
  silver/station_status  one row per (station, last_reported) telemetry event
  silver/air_quality     one row per (zone, observed_at) model observation
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


def main() -> None:
    spark = get_spark("bronze_to_silver")
    spark.sparkContext.setLogLevel("WARN")
    build_stations(spark)
    build_station_status(spark)
    build_air_quality(spark)
    spark.stop()


if __name__ == "__main__":
    main()
