"""Silver → Gold: conformed, analysis-ready tables with zone assignment.

  python -m smartcity.pipeline.silver_to_gold

Gold tables (parquet):
  gold/station_state   latest state per station, joined with dims + zone
  gold/zone_hourly     per-zone hourly aggregates: mobility x air quality
  gold/observations    unified long-format observation log (feeds the ontology)
"""
from __future__ import annotations

from pyspark.sql import functions as F
from pyspark.sql.window import Window

from smartcity.config import GOLD_DIR, SILVER_DIR, zones
from smartcity.pipeline.session import get_spark


def main() -> None:
    spark = get_spark("silver_to_gold")
    spark.sparkContext.setLogLevel("WARN")

    stations = spark.read.parquet(str(SILVER_DIR / "stations"))
    status = spark.read.parquet(str(SILVER_DIR / "station_status"))
    air = spark.read.parquet(str(SILVER_DIR / "air_quality"))

    # --- zone assignment: nearest zone center via broadcast cross-join -------
    zone_df = spark.createDataFrame(
        [(z["slug"], z["name"], float(z["lat"]), float(z["lon"])) for z in zones()],
        ["zone", "zone_name", "zone_lat", "zone_lon"],
    )
    # haversine distance in km, pure column arithmetic (no UDF)
    d = (
        F.asin(
            F.sqrt(
                F.pow(F.sin(F.radians(F.col("zone_lat") - F.col("lat")) / 2), 2)
                + F.cos(F.radians("lat"))
                * F.cos(F.radians("zone_lat"))
                * F.pow(F.sin(F.radians(F.col("zone_lon") - F.col("lon")) / 2), 2)
            )
        )
        * 2
        * 6371.0
    )
    w_near = Window.partitionBy("station_id").orderBy("dist_km")
    station_zone = (
        stations.crossJoin(F.broadcast(zone_df))
        .withColumn("dist_km", d)
        .withColumn("rn", F.row_number().over(w_near))
        .where("rn = 1")
        .select("station_id", "name", "lat", "lon", "capacity", "zone", "zone_name",
                F.round("dist_km", 3).alias("zone_dist_km"))
    )

    # --- gold/station_state: latest telemetry per station --------------------
    w_latest = Window.partitionBy("station_id").orderBy(F.desc("reported_at"))
    latest_status = status.withColumn("rn", F.row_number().over(w_latest)).where("rn = 1").drop("rn")
    station_state = (
        station_zone.join(latest_status, "station_id", "left")
        .withColumn(
            "fill_ratio",
            F.when(F.col("capacity") > 0, F.col("bikes_available") / F.col("capacity")),
        )
    )
    station_state.write.mode("overwrite").parquet(str(GOLD_DIR / "station_state"))
    print(f"gold/station_state: {station_state.count()} stations")

    # --- gold/zone_hourly: mobility x environment per zone per hour ----------
    mobility = (
        status.join(station_zone.select("station_id", "zone"), "station_id")
        .withColumn("hour", F.date_trunc("hour", "reported_at"))
        .groupBy("zone", "hour")
        .agg(
            F.round(F.avg("bikes_available"), 2).alias("avg_bikes_available"),
            F.round(F.avg(F.when(F.col("bikes_available") == 0, 1).otherwise(0)) * 100, 1).alias("pct_stations_empty"),
            F.round(F.avg(F.when(F.col("docks_available") == 0, 1).otherwise(0)) * 100, 1).alias("pct_stations_full"),
            F.countDistinct("station_id").alias("stations_reporting"),
        )
    )
    air_hourly = (
        air.withColumn("hour", F.date_trunc("hour", "observed_at"))
        .groupBy("zone", "hour")
        .agg(
            F.round(F.avg("pm2_5"), 2).alias("pm2_5"),
            F.round(F.avg("pm10"), 2).alias("pm10"),
            F.round(F.avg("no2"), 2).alias("no2"),
            F.round(F.avg("o3"), 2).alias("o3"),
            F.round(F.avg("eaqi"), 1).alias("eaqi"),
        )
    )
    zone_hourly = mobility.join(air_hourly, ["zone", "hour"], "full_outer")
    zone_hourly.write.mode("overwrite").parquet(str(GOLD_DIR / "zone_hourly"))
    print(f"gold/zone_hourly: {zone_hourly.count()} zone-hours")

    # --- gold/observations: unified long-format log (ontology feedstock) -----
    station_obs = (
        status.join(station_zone.select("station_id", "zone"), "station_id")
        .select(
            F.concat(F.lit("station:"), "station_id").alias("entity_id"),
            F.lit("BikeStation").alias("entity_type"),
            "zone",
            F.col("reported_at").alias("observed_at"),
            F.explode(
                F.create_map(
                    F.lit("bikes_available"), F.col("bikes_available").cast("double"),
                    F.lit("docks_available"), F.col("docks_available").cast("double"),
                )
            ).alias("metric", "value"),
        )
    )
    air_obs = air.select(
        F.concat(F.lit("aq:"), "zone").alias("entity_id"),
        F.lit("AirQualitySensor").alias("entity_type"),
        "zone",
        "observed_at",
        F.explode(
            F.create_map(
                F.lit("pm2_5"), "pm2_5",
                F.lit("pm10"), "pm10",
                F.lit("no2"), "no2",
                F.lit("o3"), "o3",
                F.lit("eaqi"), "eaqi",
            )
        ).alias("metric", "value"),
    )
    observations = station_obs.unionByName(air_obs).where(F.col("value").isNotNull())
    observations.write.mode("overwrite").parquet(str(GOLD_DIR / "observations"))
    print(f"gold/observations: {observations.count()} observations")

    spark.stop()


if __name__ == "__main__":
    main()
