"""Confirmed-table gathering inventory, durable rooms, notifications and exceptions."""

from alembic import op

revision = "0011_gathering"
down_revision = "0010_match_resolution"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE chat_room(id uuid PRIMARY KEY,
        dining_table_id uuid NOT NULL UNIQUE REFERENCES dining_table(id),
        created_at timestamptz NOT NULL)""")
    op.execute("""CREATE TABLE chat_message(id bigserial PRIMARY KEY,
        room_id uuid NOT NULL REFERENCES chat_room(id), author_id uuid REFERENCES app_user(id),
        kind varchar(16) NOT NULL CHECK(kind IN ('SYSTEM','USER')), request_key uuid,
        event_key text, body text NOT NULL CHECK(length(body) BETWEEN 1 AND 2000),
        created_at timestamptz NOT NULL,
        CHECK((kind='USER' AND author_id IS NOT NULL AND request_key IS NOT NULL AND event_key IS NULL)
          OR (kind='SYSTEM' AND author_id IS NULL AND request_key IS NULL AND event_key IS NOT NULL)),
        UNIQUE(room_id,author_id,request_key), UNIQUE(room_id,event_key))""")
    op.execute("CREATE INDEX chat_message_room_cursor ON chat_message(room_id,id)")
    op.execute("""CREATE TABLE app_notification(id uuid PRIMARY KEY,user_id uuid NOT NULL
        REFERENCES app_user(id),event_key text NOT NULL,kind text NOT NULL,title text NOT NULL,
        body text NOT NULL,url text NOT NULL,created_at timestamptz NOT NULL,read_at timestamptz,
        UNIQUE(user_id,event_key))""")
    op.execute("""CREATE TABLE push_subscription(id uuid PRIMARY KEY,user_id uuid NOT NULL
        REFERENCES app_user(id),endpoint text NOT NULL UNIQUE,p256dh text NOT NULL,auth text NOT NULL,
        created_at timestamptz NOT NULL,active boolean NOT NULL DEFAULT true)""")
    op.execute("""CREATE TABLE push_delivery(id uuid PRIMARY KEY,notification_id uuid NOT NULL
        REFERENCES app_notification(id),subscription_id uuid NOT NULL REFERENCES push_subscription(id),
        state text NOT NULL CHECK(state IN ('PENDING','SENT','FAILED','UNAVAILABLE')),
        attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3),
        next_attempt_at timestamptz NOT NULL,last_error_code text,sent_at timestamptz,
        UNIQUE(notification_id,subscription_id))""")
    op.execute(
        "CREATE INDEX push_delivery_due ON push_delivery(next_attempt_at) WHERE state='PENDING'"
    )
    op.execute("""CREATE TABLE gathering_exception(id uuid PRIMARY KEY,
        dining_table_id uuid REFERENCES dining_table(id),event_key text NOT NULL UNIQUE,
        kind text NOT NULL,state text NOT NULL CHECK(state IN ('OPEN','RESOLVED')),
        reason_code text NOT NULL,created_at timestamptz NOT NULL,updated_at timestamptz NOT NULL)""")
    op.execute("""CREATE TABLE venue_inventory(id uuid PRIMARY KEY,event_slot_id uuid NOT NULL
        REFERENCES event_slot(id),name text NOT NULL,address text NOT NULL,map_url text NOT NULL,
        price_krw integer NOT NULL CHECK(price_krw>=10000),capacity integer NOT NULL
        CHECK(capacity BETWEEN 4 AND 100),active boolean NOT NULL DEFAULT true,
        created_by uuid NOT NULL REFERENCES app_user(id),created_at timestamptz NOT NULL)""")
    op.execute("""CREATE TABLE venue_food_approval(inventory_id uuid REFERENCES venue_inventory(id),
        dining_table_id uuid REFERENCES dining_table(id),food_snapshot text NOT NULL,
        reviewed_by uuid NOT NULL REFERENCES app_user(id),created_at timestamptz NOT NULL,
        PRIMARY KEY(inventory_id,dining_table_id,food_snapshot))""")
    op.execute("""CREATE TABLE venue_allocation(id uuid PRIMARY KEY,dining_table_id uuid NOT NULL
        UNIQUE REFERENCES dining_table(id),inventory_id uuid NOT NULL UNIQUE
        REFERENCES venue_inventory(id),reservation_name text NOT NULL,created_at timestamptz NOT NULL)""")


def downgrade():
    for name in (
        "venue_allocation",
        "venue_food_approval",
        "venue_inventory",
        "gathering_exception",
        "push_delivery",
        "push_subscription",
        "app_notification",
        "chat_message",
        "chat_room",
    ):
        op.drop_table(name)
