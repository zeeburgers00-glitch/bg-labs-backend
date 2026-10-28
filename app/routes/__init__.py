"""BG LABS route package.

Sub-modules are imported explicitly by ``main.py`` - this package must not import
them eagerly. Several optional routers pull in SQLAlchemy (and the XTTS stack via
``app.services``), which are not installed in the serverless build; an eager
import here would stop the API from booting on Vercel.
"""

__all__: list = []
