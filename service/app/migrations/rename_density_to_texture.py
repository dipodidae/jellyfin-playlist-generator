"""
Migration: Rename density column to texture in track_profiles table.

This migration renames the 'density' column to 'texture' to better reflect
the semantic meaning (complexity, layering, distortion) of this dimension.
"""

import logging
from app.database_pg import get_connection

logger = logging.getLogger(__name__)


def migrate():
    """Rename density column to texture if it exists."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Check if density column exists
            cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'track_profiles' AND column_name = 'density'
            """)
            
            if cur.fetchone():
                logger.info("Renaming 'density' column to 'texture' in track_profiles")
                cur.execute("""
                    ALTER TABLE track_profiles 
                    RENAME COLUMN density TO texture
                """)
                conn.commit()
                logger.info("Migration complete: density -> texture")
            else:
                # Check if texture already exists
                cur.execute("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'track_profiles' AND column_name = 'texture'
                """)
                if cur.fetchone():
                    logger.info("Column 'texture' already exists, no migration needed")
                else:
                    logger.warning("Neither 'density' nor 'texture' column found in track_profiles")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate()
