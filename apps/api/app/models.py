"""Import every module's models so SQLAlchemy metadata (and Alembic) sees all tables."""

from app.core.db import Base  # noqa: F401
from app.modules.assessment.models import *  # noqa: F401,F403
from app.modules.catalog.models import *  # noqa: F401,F403
from app.modules.content.models import *  # noqa: F401,F403
from app.modules.identity.models import *  # noqa: F401,F403
from app.modules.ingest.models import *  # noqa: F401,F403
from app.modules.learning.models import *  # noqa: F401,F403
