import os
from datetime import datetime
from pathlib import Path
import tomllib

import streamlit as st
from pymongo import MongoClient
from pymongo.errors import PyMongoError

MONGODB_URI_ENV = "MONGODB_URI"
MONGODB_DB_ENV = "MONGODB_DB"
DEFAULT_DB_NAME = "attendly"


def get_mongo_uri():
    uri = None
    checked_sources = []

    if hasattr(st, "secrets") and "mongodb" in st.secrets:
        uri = st.secrets.mongodb.get("uri")
        checked_sources.append("Streamlit secrets")

    env_uri = os.environ.get(MONGODB_URI_ENV)
    if env_uri:
        uri = uri or env_uri
    checked_sources.append("MONGODB_URI environment variable")

    if not uri:
        secrets_path = Path(__file__).parent / ".streamlit" / "secrets.toml"
        if secrets_path.exists():
            try:
                with secrets_path.open("rb") as f:
                    secrets = tomllib.load(f)
                uri = secrets.get("mongodb", {}).get("uri")
                checked_sources.append(".streamlit/secrets.toml")
            except Exception:
                uri = None

    if not uri:
        sources = ", ".join(checked_sources)
        raise ValueError(
            "MongoDB URI not found. Checked: "
            f"{sources}. Set the MONGODB_URI environment variable or add it to `.streamlit/secrets.toml` under [mongodb]."
        )
    return uri


def get_database(uri: str | None = None, db_name: str | None = None):
    uri = uri or get_mongo_uri()
    if db_name is None:
        if hasattr(st, "secrets") and "mongodb" in st.secrets:
            db_name = st.secrets.mongodb.get("db")
        db_name = db_name or os.environ.get(MONGODB_DB_ENV, DEFAULT_DB_NAME)
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    return client[db_name]


def get_events_collection(uri: str | None = None, db_name: str | None = None):
    return get_database(uri=uri, db_name=db_name)["events"]


def get_registrations_collection(uri: str | None = None, db_name: str | None = None):
    return get_database(uri=uri, db_name=db_name)["registrations"]


def generate_event_id(events):
    existing_ids = [int(event["id"][2:]) for event in events if event["id"].startswith("Ev")]
    next_id = max(existing_ids, default=0) + 1
    return f"Ev{next_id:03d}"


def create_event_payload(name: str, event_id: str):
    return {
        "id": event_id,
        "name": name.strip(),
        "created_at": datetime.utcnow().isoformat() + "Z",
    }


def insert_event(events_collection, name: str):
    name = name.strip()
    if not name:
        raise ValueError("Event name cannot be empty.")
    existing_ids = list(events_collection.find({}, {"id": 1}))
    event_id = generate_event_id(existing_ids)
    payload = create_event_payload(name, event_id)
    events_collection.insert_one(payload)
    return payload


def find_event_by_id(events_collection, event_id: str):
    return events_collection.find_one({"id": event_id})


def find_event_by_name(events_collection, event_name: str):
    return events_collection.find_one(
        {"name": {"$regex": f"^{event_name}$", "$options": "i"}}
    )


def list_events(events_collection):
    return list(events_collection.find({}, sort=[("id", 1)]))


def create_registration_payload(event_id: str, response: str, main_name: str, adult_count: int, child_count: int):
    return {
        "event_id": event_id,
        "response": response,
        "main_name": main_name.strip(),
        "adult_count": adult_count,
        "child_count": child_count,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }


def insert_registration(registrations_collection, event_id: str, response: str, main_name: str, adult_count: int, child_count: int):
    payload = create_registration_payload(event_id, response, main_name, adult_count, child_count)
    registrations_collection.insert_one(payload)
    return payload


def list_registrations(registrations_collection, event_id: str):
    return list(registrations_collection.find({"event_id": event_id}))


def get_attendance_totals(registrations):
    total_adults = 0
    total_children = 0
    registered_count = 0
    for registration in registrations:
        if registration["response"] in {"Yes", "Maybe"}:
            total_adults += registration["adult_count"]
            total_children += registration["child_count"]
            registered_count += 1
    return registered_count, total_adults, total_children


def get_attendee_rows(registrations):
    return [
        {
            "Main Attendee": registration["main_name"],
            "Response": registration["response"],
            "Adults": registration["adult_count"],
            "Children": registration["child_count"],
        }
        for registration in registrations
        if registration["response"] in {"Yes", "Maybe"}
    ]
