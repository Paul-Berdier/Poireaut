"""SQLAlchemy models.

Importing every model here is crucial — Alembic's autogenerate only detects
tables that are attached to the Base.metadata, which requires the model class
to have been *imported* by the time env.py calls it.
"""
from src.models.connector import Connector, ConnectorRun
from src.models.datapoint import DataPoint
from src.models.entity import Entity
from src.models.investigation import Investigation
from src.models.user import User

__all__ = [
    "User",
    "Investigation",
    "Entity",
    "DataPoint",
    "Connector",
    "ConnectorRun",
]
