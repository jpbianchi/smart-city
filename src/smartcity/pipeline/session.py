"""Shared local SparkSession."""
from __future__ import annotations

from pyspark.sql import SparkSession


def get_spark(app_name: str = "smartcity") -> SparkSession:
    return (
        SparkSession.builder.appName(app_name)
        .master("local[*]")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.driver.memory", "2g")
        .config("spark.ui.showConsoleProgress", "false")
        .getOrCreate()
    )
