"""Silver → Gold: conformed, analysis-ready tables with zone assignment.

  python -m smartcity.pipeline.silver_to_gold

Gold tables (parquet):
  gold/station_state        latest state per station, joined with dims + zone
  gold/zone_hourly          per-zone hourly aggregates: mobility x air quality
  gold/traffic_sensors      road-sensor dimension (latest name/geo + zone)
  gold/zone_traffic_hourly  per-zone hourly traffic flow/occupancy
  gold/amenities            POIs with zone
  gold/zone_amenities       per-zone amenity counts by kind
  gold/transactions         cleaned sales with zone
  gold/zone_market          per-zone median EUR/m2 by year and property type
  gold/transaction_features valuation feature matrix (one row per sale)
  gold/observations         unified long-format observation log
"""
from __future__ import annotations

from pyspark.sql import DataFrame, functions as F
from pyspark.sql.window import Window

from smartcity.config import GOLD_DIR, SILVER_DIR, zones
from smartcity.pipeline.session import get_spark

EARTH_KM = 6371.0


def _haversine_km(lat1, lon1, lat2, lon2):
    return (
        F.asin(
            F.sqrt(
                F.pow(F.sin(F.radians(lat2 - lat1) / 2), 2)
                + F.cos(F.radians(lat1)) * F.cos(F.radians(lat2))
                * F.pow(F.sin(F.radians(lon2 - lon1) / 2), 2)
            )
        )
        * 2 * EARTH_KM
    )


def _zone_df(spark):
    return spark.createDataFrame(
        [(z["slug"], z["name"], float(z["lat"]), float(z["lon"])) for z in zones()],
        ["zone", "zone_name", "zone_lat", "zone_lon"],
    )


def with_zone(df: DataFrame, zone_df: DataFrame, keep_dist: bool = False) -> DataFrame:
    """Assign every row (needs lat/lon) to its nearest zone center."""
    tagged = df.withColumn("__rid", F.monotonically_increasing_id())
    w = Window.partitionBy("__rid").orderBy("dist_km")
    out = (
        tagged.crossJoin(F.broadcast(zone_df))
        .withColumn("dist_km", _haversine_km(F.col("zone_lat"), F.col("zone_lon"),
                                             F.col("lat"), F.col("lon")))
        .withColumn("rn", F.row_number().over(w))
        .where("rn = 1")
        .drop("rn", "zone_lat", "zone_lon", "__rid")
    )
    if keep_dist:
        return out.withColumnRenamed("dist_km", "zone_dist_km")
    return out.drop("dist_km")


def _grid_cells(lat_col, lon_col, cell_lat: float, cell_lon: float):
    return (F.floor(lat_col / cell_lat).cast("long"), F.floor(lon_col / cell_lon).cast("long"))


def _neighbor_grid(df: DataFrame, cell_lat: float, cell_lon: float,
                   lat="lat", lon="lon") -> DataFrame:
    """Replicate each row into its cell and the 8 neighbors (for radius joins)."""
    cy, cx = _grid_cells(F.col(lat), F.col(lon), cell_lat, cell_lon)
    df = df.withColumn("_cy", cy).withColumn("_cx", cx)
    offsets = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
    off = df.sparkSession.createDataFrame(offsets, ["_dy", "_dx"])
    return (
        df.crossJoin(F.broadcast(off))
        .withColumn("_cy", F.col("_cy") + F.col("_dy"))
        .withColumn("_cx", F.col("_cx") + F.col("_dx"))
        .drop("_dy", "_dx")
    )


NEAREST_KINDS = {
    "subway_station": "subway",
    "train_station": "train",
    "school": "school",
    "park": "park",
}


def nearest_amenities(points: DataFrame, amen_pdf) -> DataFrame:
    """Nearest amenity of each kind for every point: (id, name, distance in m).

    Amenities are small (a few thousand rows), so one haversine BallTree per
    kind is built on the driver, broadcast, and queried partition-by-partition
    with mapInPandas — O(n log m) instead of an n x m cross join.
    """
    import numpy as np
    import pandas as pd
    from pyspark.sql.types import DoubleType, StringType, StructField, StructType
    from sklearn.neighbors import BallTree

    trees = {}
    for kind in NEAREST_KINDS:
        sub = amen_pdf[amen_pdf["kind"] == kind].reset_index(drop=True)
        if not sub.empty:
            tree = BallTree(np.radians(sub[["lat", "lon"]].to_numpy()), metric="haversine")
            trees[kind] = (tree, sub["osm_id"].tolist(), sub["name"].fillna("").tolist())
    bc = points.sparkSession.sparkContext.broadcast(trees)

    fields = [StructField("tx_id", StringType())]
    for short in NEAREST_KINDS.values():
        fields += [
            StructField(f"{short}_id", StringType()),
            StructField(f"{short}_name", StringType()),
            StructField(f"dist_{short}_m", DoubleType()),
        ]
    schema = StructType(fields)

    def _query(batches):
        local = bc.value
        for pdf in batches:
            out = pd.DataFrame({"tx_id": pdf["tx_id"]})
            coords = np.radians(pdf[["lat", "lon"]].to_numpy())
            for kind, short in NEAREST_KINDS.items():
                if kind not in local or len(pdf) == 0:
                    out[f"{short}_id"], out[f"{short}_name"], out[f"dist_{short}_m"] = None, None, np.nan
                    continue
                tree, ids, names = local[kind]
                dist, idx = tree.query(coords, k=1)
                idx = idx[:, 0]
                out[f"{short}_id"] = [ids[i] for i in idx]
                out[f"{short}_name"] = [names[i] or None for i in idx]
                out[f"dist_{short}_m"] = np.round(dist[:, 0] * EARTH_KM * 1000, 0)
            yield out

    return points.mapInPandas(_query, schema=schema)


def main() -> None:
    spark = get_spark("silver_to_gold")
    spark.sparkContext.setLogLevel("WARN")
    zone_df = _zone_df(spark)

    stations = spark.read.parquet(str(SILVER_DIR / "stations"))
    status = spark.read.parquet(str(SILVER_DIR / "station_status"))
    air = spark.read.parquet(str(SILVER_DIR / "air_quality"))
    traffic = spark.read.parquet(str(SILVER_DIR / "traffic_readings"))
    sales = spark.read.parquet(str(SILVER_DIR / "transactions"))
    amenities = spark.read.parquet(str(SILVER_DIR / "amenities"))

    # --- stations: zone + latest state (unchanged behaviour) -----------------
    station_zone = with_zone(
        stations.select("station_id", "name", "lat", "lon", "capacity"), zone_df, keep_dist=True
    ).withColumn("zone_dist_km", F.round("zone_dist_km", 3))
    w_latest = Window.partitionBy("station_id").orderBy(F.desc("reported_at"))
    latest_status = status.withColumn("rn", F.row_number().over(w_latest)).where("rn = 1").drop("rn")
    station_state = station_zone.join(latest_status, "station_id", "left").withColumn(
        "fill_ratio",
        F.when(F.col("capacity") > 0, F.col("bikes_available") / F.col("capacity")),
    )
    station_state.write.mode("overwrite").parquet(str(GOLD_DIR / "station_state"))
    print(f"gold/station_state: {station_state.count()} stations")

    # --- zone_hourly: mobility x environment ---------------------------------
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

    # --- traffic: sensor dim + per-zone hourly --------------------------------
    w_sensor = Window.partitionBy("sensor_id").orderBy(F.desc("observed_at"))
    sensor_dim = (
        traffic.withColumn("rn", F.row_number().over(w_sensor)).where("rn = 1")
        .select("sensor_id", "name", "lat", "lon",
                F.col("observed_at").alias("last_seen"),
                F.col("flow_vph").alias("last_flow_vph"),
                F.col("occupancy_pct").alias("last_occupancy_pct"),
                F.col("state").alias("last_state"))
    )
    traffic_sensors = with_zone(sensor_dim, zone_df)
    traffic_sensors.write.mode("overwrite").parquet(str(GOLD_DIR / "traffic_sensors"))
    print(f"gold/traffic_sensors: {traffic_sensors.count()} sensors")

    sensor_zone = traffic_sensors.select("sensor_id", "zone")
    zone_traffic_hourly = (
        traffic.join(sensor_zone, "sensor_id")
        .groupBy("zone", F.date_trunc("hour", "observed_at").alias("hour"))
        .agg(
            F.round(F.avg("flow_vph"), 1).alias("avg_flow_vph"),
            F.round(F.avg("occupancy_pct"), 2).alias("avg_occupancy_pct"),
            F.countDistinct("sensor_id").alias("sensors_reporting"),
        )
    )
    zone_traffic_hourly.write.mode("overwrite").parquet(str(GOLD_DIR / "zone_traffic_hourly"))
    print(f"gold/zone_traffic_hourly: {zone_traffic_hourly.count()} zone-hours")

    # --- amenities -------------------------------------------------------------
    amen_zone = with_zone(amenities, zone_df)
    amen_zone.write.mode("overwrite").parquet(str(GOLD_DIR / "amenities"))
    zone_amenities = amen_zone.groupBy("zone").pivot("kind").count().na.fill(0)
    zone_amenities.write.mode("overwrite").parquet(str(GOLD_DIR / "zone_amenities"))
    print(f"gold/amenities: {amen_zone.count()} POIs")

    # --- transactions + market -------------------------------------------------
    tx_zone = with_zone(sales, zone_df)
    tx_zone = tx_zone.withColumn("tx_id", F.concat(F.lit("tx:"), "id_mutation", F.lit(":"), "id_parcelle"))
    tx_zone.write.mode("overwrite").parquet(str(GOLD_DIR / "transactions"))
    print(f"gold/transactions: {tx_zone.count()} sales")

    zone_market = (
        tx_zone.groupBy("zone", "year", "property_type")
        .agg(
            F.expr("percentile_approx(price_m2, 0.5)").alias("median_price_m2"),
            F.count("*").alias("n_sales"),
        )
    )
    zone_market.write.mode("overwrite").parquet(str(GOLD_DIR / "zone_market"))
    print(f"gold/zone_market: {zone_market.count()} zone-year-type rows")

    # --- valuation feature matrix ----------------------------------------------
    # nearest metro / train / school / park, by name and distance
    amen_pdf = amen_zone.where(F.col("kind").isin(*NEAREST_KINDS)).select(
        "osm_id", "kind", "name", "lat", "lon"
    ).toPandas()
    tx_nearest = nearest_amenities(tx_zone.select("tx_id", "lat", "lon"), amen_pdf)

    # counts within 500m via 3x3 grid-cell join (cells ~500m)
    CELL_LAT, CELL_LON = 0.0045, 0.0068
    cy, cx = _grid_cells(F.col("lat"), F.col("lon"), CELL_LAT, CELL_LON)
    tx_cells = tx_zone.select("tx_id", "lat", "lon").withColumn("_cy", cy).withColumn("_cx", cx)
    amen_grid = _neighbor_grid(
        amen_zone.where(F.col("kind").isin("school", "park", "supermarket"))
        .select("kind", F.col("lat").alias("a_lat"), F.col("lon").alias("a_lon"))
        .withColumnRenamed("a_lat", "lat").withColumnRenamed("a_lon", "lon"),
        CELL_LAT, CELL_LON,
    ).withColumnRenamed("lat", "a_lat").withColumnRenamed("lon", "a_lon")
    near_counts = (
        tx_cells.join(amen_grid, ["_cy", "_cx"])
        .where(_haversine_km(F.col("lat"), F.col("lon"), F.col("a_lat"), F.col("a_lon")) <= 0.5)
        .groupBy("tx_id").pivot("kind", ["school", "park", "supermarket"]).count()
        .na.fill(0)
        .withColumnRenamed("school", "n_schools_500m")
        .withColumnRenamed("park", "n_parks_500m")
        .withColumnRenamed("supermarket", "n_supermarkets_500m")
    )

    # per-zone ambient indicators (static-ish context features)
    zone_traffic_mean = (
        zone_traffic_hourly.groupBy("zone")
        .agg(F.round(F.avg("avg_occupancy_pct"), 2).alias("zone_traffic_occupancy"))
    )
    zone_air_mean = air.groupBy("zone").agg(F.round(F.avg("eaqi"), 1).alias("zone_eaqi"))

    features = (
        tx_zone.select(
            "tx_id", "zone", "property_type", "surface_m2", "rooms", "price_eur",
            "price_m2", "year", "sold_on", "lat", "lon", "postal_code", "address",
            F.months_between(F.col("sold_on"), F.lit("2021-01-01")).cast("int").alias("month_index"),
        )
        .join(tx_nearest, "tx_id", "left")
        .join(near_counts, "tx_id", "left")
        .join(zone_traffic_mean, "zone", "left")
        .join(zone_air_mean, "zone", "left")
        .na.fill({"n_schools_500m": 0, "n_parks_500m": 0, "n_supermarkets_500m": 0})
    )
    features.write.mode("overwrite").parquet(str(GOLD_DIR / "transaction_features"))
    print(f"gold/transaction_features: {features.count()} rows")

    # --- unified observation log (ontology feedstock) ---------------------------
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
                F.lit("pm2_5"), "pm2_5", F.lit("pm10"), "pm10",
                F.lit("no2"), "no2", F.lit("o3"), "o3", F.lit("eaqi"), "eaqi",
            )
        ).alias("metric", "value"),
    )
    traffic_obs = (
        traffic.join(sensor_zone, "sensor_id")
        .select(
            F.concat(F.lit("traffic:"), "sensor_id").alias("entity_id"),
            F.lit("TrafficSensor").alias("entity_type"),
            "zone",
            "observed_at",
            F.explode(
                F.create_map(
                    F.lit("flow_vph"), "flow_vph",
                    F.lit("occupancy_pct"), "occupancy_pct",
                )
            ).alias("metric", "value"),
        )
    )
    observations = (
        station_obs.unionByName(air_obs).unionByName(traffic_obs)
        .where(F.col("value").isNotNull())
    )
    observations.write.mode("overwrite").parquet(str(GOLD_DIR / "observations"))
    print(f"gold/observations: {observations.count()} observations")

    spark.stop()


if __name__ == "__main__":
    main()
