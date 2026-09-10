"""add subscriptions and subscription_posts

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-10

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Use raw SQL to reference the existing platform enum type
    op.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
            platform platform NOT NULL,
            source_url VARCHAR(2048) NOT NULL,
            source_id VARCHAR(255) NOT NULL,
            name VARCHAR(255) NOT NULL,
            screen_name VARCHAR(255) NOT NULL DEFAULT '',
            photo_url VARCHAR(1024) NOT NULL DEFAULT '',
            is_active BOOLEAN DEFAULT TRUE,
            backfill BOOLEAN DEFAULT FALSE,
            backfill_completed BOOLEAN DEFAULT FALSE,
            check_interval_minutes INTEGER DEFAULT 300,
            last_checked_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_subscriptions_user_id ON subscriptions(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_subscriptions_message_id ON subscriptions(message_id)")
    op.execute("DO $$ BEGIN ALTER TABLE subscriptions ADD CONSTRAINT uq_subscription_source UNIQUE (platform, source_id); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")

    op.execute("""
        CREATE TABLE IF NOT EXISTS subscription_posts (
            id SERIAL PRIMARY KEY,
            subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
            post_external_id VARCHAR(255) NOT NULL,
            link_id INTEGER REFERENCES links(id) ON DELETE SET NULL,
            post_created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            first_seen_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_subscription_posts_subscription_id ON subscription_posts(subscription_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_subscription_posts_link_id ON subscription_posts(link_id)")
    op.execute("DO $$ BEGIN ALTER TABLE subscription_posts ADD CONSTRAINT uq_subscription_post UNIQUE (subscription_id, post_external_id); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS subscription_posts")
    op.execute("DROP TABLE IF EXISTS subscriptions")
