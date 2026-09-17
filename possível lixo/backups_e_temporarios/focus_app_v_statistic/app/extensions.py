"""
Extensões compartilhadas do Flask.

Mantidas em módulo separado para evitar import circular entre
app/__init__.py (application factory) e app/models.py.
"""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
