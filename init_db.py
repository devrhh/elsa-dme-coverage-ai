"""Schema creation + sample organization seeding.

Organizations are fixed reference data (no create/update/delete API - see
app/routers/organizations.py), so seeding a handful of sample organizations
here is the only way to populate them.
"""

from app.db.models import Document, Interaction, InteractionDocument, Organization  # noqa: F401
from app.db.session import Base, SessionLocal, engine

SAMPLE_ORGANIZATIONS = ["Acme DME", "MedSupply Co", "HomeHealth Partners"]


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    print("Database schema created (or already up to date).")
    seed_organizations()


def seed_organizations() -> None:
    db = SessionLocal()
    try:
        existing_names = {name for (name,) in db.query(Organization.name).all()}
        created = 0
        for name in SAMPLE_ORGANIZATIONS:
            if name in existing_names:
                continue
            db.add(Organization(name=name))
            created += 1
        db.commit()
        print(f"Seeded {created} organization(s); {len(SAMPLE_ORGANIZATIONS)} total sample organizations available.")
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
