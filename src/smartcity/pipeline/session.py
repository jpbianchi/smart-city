"""Shared local SparkSession."""
from __future__ import annotations

import os
import sys

from pyspark.sql import SparkSession


def get_spark(app_name: str = "smartcity") -> SparkSession:
    # Python workers must use the same interpreter (and site-packages) as the
    # driver, or pandas-based transforms fail with ModuleNotFoundError.
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)
    return (
        SparkSession.builder.appName(app_name)
        .master("local[*]")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.driver.memory", "2g")
        .config("spark.ui.showConsoleProgress", "false")
        .getOrCreate()
    )
