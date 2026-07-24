import os
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from pymongo.errors import PyMongoError
import logging

from mongodbhelper import (
    get_events_collection,
    get_registrations_collection,
    insert_event,
    insert_registration,
    list_events,
    list_registrations,
    get_attendance_totals,
    get_attendee_rows,
    find_event_by_name,
    find_event_by_id,
)

st.set_page_config(page_title="Attendly", page_icon="🎉", layout="wide")

SESSION_SELECTED_EVENT = "selected_event_id"
SESSION_INFO_EVENT = "info_event_id"

# Backwards-compatibility flag: some deployed instances may still reference
# `route_active`. Define it here to avoid NameError during a rolling deploy.
route_active = False

# Demo fallback data so the app still works when MongoDB is not configured.
FALLBACK_EVENTS = [{"id": "Ev001", "name": "Family"}]
FALLBACK_REGISTRATIONS = {
    "Ev001": [{"response": "Yes", "main_name": "Demo attendee", "adult_count": 2, "child_count": 1}],
}


def load_css():
    css_path = Path(__file__).parent / ".streamlit" / "theme.css"
    if css_path.exists():
        st.markdown(
            f"<style>{css_path.read_text()}</style>",
            unsafe_allow_html=True,
        )


def init_session_state():
    if SESSION_SELECTED_EVENT not in st.session_state:
        st.session_state[SESSION_SELECTED_EVENT] = None
    if SESSION_INFO_EVENT not in st.session_state:
        st.session_state[SESSION_INFO_EVENT] = None
    if "_debug_logs" not in st.session_state:
        st.session_state["_debug_logs"] = []


def _debug(msg: str):
    """Log to server logs and store a copy for display in the app sidebar."""
    try:
        logging.debug(msg)
    except Exception:
        pass
    try:
        st.session_state["_debug_logs"].append(str(msg))
    except Exception:
        # If Streamlit isn't fully initialized, still print to stdout for logs
        print(msg)


def _coerce_query_value(value):
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def get_route_selection():
    # Normalize query param keys to be case-insensitive (some hosts may change casing)
    params = {k.lower(): v for k, v in st.query_params.items()}
    _debug(f"Raw query params: {st.query_params}")
    event_id = _coerce_query_value(params.get("event"))
    info_raw = _coerce_query_value(params.get("info"))
    info = str(info_raw or "").lower() in {"1", "true", "yes"}
    return event_id, info


def load_static_html(filename: str) -> str:
    html_path = Path(__file__).parent / "static" / filename
    if not html_path.exists():
        raise FileNotFoundError(f"Missing static route template: {html_path}")
    return html_path.read_text()


# Simplified navigation: use query-params only. No JS-based path rewriting.


def render_attendance_html(event):
    template = load_static_html("attendance.html")
    html = template.replace("{event_name}", event["name"]).replace("{event_id}", event["id"])
    debug_message = f"Rendering attendance HTML for event_id={event['id']}"
    _debug(debug_message)
    _debug(html[:2000])
    html += f"\n<script>console.log({repr(debug_message)});</script>"
    st.html(html, unsafe_allow_javascript=True)


def render_info_html(event, registrations):
    template = load_static_html("info.html")
    registered_count, total_adults, total_children = get_attendance_totals(registrations)
    rows = get_attendee_rows(registrations)
    rows_html = "\n".join(
        f"<tr><td>{row['main_name']}</td><td>{row['response']}</td><td>{row['adult_count']}</td><td>{row['child_count']}</td></tr>"
        for row in rows
    )
    html = (
        template
        .replace("{event_name}", event["name"])
        .replace("{event_id}", event["id"])
        .replace("{registered_count}", str(registered_count))
        .replace("{total_adults}", str(total_adults))
        .replace("{total_children}", str(total_children))
        .replace("{rows}", rows_html)
    )
    debug_message = (
        f"Rendering info HTML for event_id={event['id']} registered={registered_count} adults={total_adults} children={total_children}"
    )
    _debug(debug_message)
    _debug(html[:3000])
    html += f"\n<script>console.log({repr(debug_message)});</script>"
    st.html(html, unsafe_allow_javascript=True)


def _insert_registration_record(registrations_collection, event_id, response, main_name, adult_count, child_count):
    payload = {
        "event_id": event_id,
        "response": response,
        "main_name": main_name.strip(),
        "adult_count": adult_count,
        "child_count": child_count,
    }
    if registrations_collection is None:
        FALLBACK_REGISTRATIONS.setdefault(event_id, []).append(payload)
        return payload
    return insert_registration(registrations_collection, event_id, response, main_name, adult_count, child_count)


def process_attendance_submission(event, registrations_collection):
    params = st.query_params
    if _coerce_query_value(params.get("submit")) != "1":
        return False

    response = _coerce_query_value(params.get("response")) or ""
    main_name = (_coerce_query_value(params.get("name")) or "").strip()
    adult_count = int(_coerce_query_value(params.get("adult_count")) or 0)
    child_count = int(_coerce_query_value(params.get("child_count")) or 0)

    if response not in {"Yes", "No", "Maybe"}:
        st.warning("Please select a valid response.")
        return True

    if response == "No":
        _insert_registration_record(registrations_collection, event["id"], response, "No attendee", 0, 0)
        st.session_state["attendance_success"] = "Your attendance response has been recorded as No."
        return True

    if not main_name:
        st.warning("Please enter the main attendee name.")
        return True

    _insert_registration_record(registrations_collection, event["id"], response, main_name, adult_count, child_count)
    st.session_state["attendance_success"] = (
        f"Saved: {main_name} ({response}) with {adult_count} adult(s) and {child_count} child(ren)."
    )
    return True


def render_event_info(event, registrations):
    registered_count, total_adults, total_children = get_attendance_totals(registrations)
    st.markdown("### Attendance summary")
    if registered_count == 0:
        st.info("No attendees have registered yet.")
        return
    st.markdown(
        f"- **Registered responses:** {registered_count}"
        f"\n- **Total adults:** {total_adults}"
        f"\n- **Total children:** {total_children}"
    )
    st.markdown("---")
    st.markdown("### Grouped by main attendee")
    rows = get_attendee_rows(registrations)
    st.table(rows)
    st.markdown(
        f"**Subtotal adults:** {total_adults}  \\"
        f"**Subtotal children:** {total_children}  \\"
        f"**Total participants:** {total_adults + total_children}"
    )


def render_event_action(event, registrations_collection):
    st.header(f"Event: {event['name']} ({event['id']})")
    st.markdown("Choose your attendance response below.")
    with st.form("attendance_form"):
        response = st.radio("I will attend:", ["Yes", "No", "Maybe"], index=2)
        main_name = ""
        adult_count = 0
        child_count = 0
        if response in {"Yes", "Maybe"}:
            main_name = st.text_input("Main attendee name")
            adult_count = st.number_input(
                "Adult count",
                min_value=1,
                max_value=10,
                value=1,
                step=1,
                help="Number of adults in this RSVP (1-10).",
            )
            child_count = st.number_input(
                "Child count",
                min_value=0,
                max_value=10,
                value=0,
                step=1,
                help="Number of children in this RSVP (0-10).",
            )
        submit = st.form_submit_button("Save RSVP")
        if submit:
            if response in {"Yes", "Maybe"} and not main_name.strip():
                st.warning("Please enter the main attendee name.")
            else:
                if response == "No":
                    insert_registration(registrations_collection, event["id"], response, "No attendee", 0, 0)
                    st.success("Your attendance response has been recorded as No.")
                else:
                    insert_registration(registrations_collection, event["id"], response, main_name, adult_count, child_count)
                    st.success(
                        f"Saved: {main_name} ({response}) with {adult_count} adult(s) and {child_count} child(ren)."
                    )
                st.session_state[SESSION_SELECTED_EVENT] = None
                st.session_state[SESSION_INFO_EVENT] = None
                st.markdown("[Back to events](/)")
                st.rerun()

def _insert_event_record(events_collection, event_name):
    if events_collection is None:
        payload = {"id": "Ev999", "name": event_name.strip()}
        FALLBACK_EVENTS.append(payload)
        return payload
    return insert_event(events_collection, event_name)


def create_event_section(events_collection):
    st.markdown("## Create a new event")
    with st.form("create_event_form"):
        event_name = st.text_input("Event name", placeholder="Enter a unique event name")
        create = st.form_submit_button("Create event")
        if create:
            event_name = event_name.strip()
            if not event_name:
                st.warning("Event name cannot be empty.")
            elif events_collection is None:
                if any(str(event.get("name", "")).lower() == event_name.lower() for event in FALLBACK_EVENTS):
                    st.warning("An event with that name already exists. Choose a unique name.")
                else:
                    _insert_event_record(events_collection, event_name)
                    st.success(f"Event '{event_name}' created.")
                    st.rerun()
            elif find_event_by_name(events_collection, event_name):
                st.warning("An event with that name already exists. Choose a unique name.")
            else:
                _insert_event_record(events_collection, event_name)
                st.success(f"Event '{event_name}' created.")
                st.rerun()


def main():
    init_session_state()
    load_css()

    # Use query params for routing: ?event=<id> and optional &info=true
    route_event_id, route_info = get_route_selection()
    debug_mode = str(_coerce_query_value(st.query_params.get("debug")) or "").lower() in {"1", "true", "yes"}

    st.title("Attendly")
    st.markdown("Create and manage event RSVPs with mobile-friendly layout.")
    _debug(f"Starting main(); route_event_id={route_event_id!r}, route_info={route_info!r}")
    st.markdown("### Debug trace")
    st.code("\n".join(st.session_state.get("_debug_logs", [])[-10:]), language="text")

    events_collection = None
    registrations_collection = None
    try:
        from mongodbhelper import get_mongo_uri, get_database

        mongo_uri = get_mongo_uri()
        db_name = None
        if hasattr(st, "secrets") and "mongodb" in st.secrets:
            db_name = st.secrets.mongodb.get("db")
        db_name = db_name or os.environ.get("MONGODB_DB", "attendly")

        if debug_mode:
            st.caption(f"Debug Mongo URI: {mongo_uri}")
            st.caption(f"Debug DB name: {db_name}")
            print(f"[attendly-debug] Mongo URI: {mongo_uri}")
            print(f"[attendly-debug] Mongo DB: {db_name}")

        events_collection = get_events_collection()
        registrations_collection = get_registrations_collection()
    except (PyMongoError, ValueError) as error:
        st.warning(f"MongoDB not configured; using demo data: {error}")
        _debug(f"MongoDB connection failed: {error}")
        events_collection = None
        registrations_collection = None

    all_events = list(FALLBACK_EVENTS) if events_collection is None else list_events(events_collection)
    _debug(f"Loaded {len(all_events)} events from {'demo data' if events_collection is None else 'DB'}")

    # If an event is specified in query params, render its view directly.
    if route_event_id:
        # Try direct DB lookup first, then fall back to in-memory list matches.
        try:
            if events_collection is None:
                active_event = None
            else:
                active_event = find_event_by_id(events_collection, route_event_id)
        except Exception:
            active_event = None
        if not active_event:
            # case-insensitive or prefix match fallback
            active_event = next(
                (event for event in all_events if str(event.get("id", "")).lower() == str(route_event_id).lower()),
                None,
            )
        if not active_event:
            active_event = next(
                (event for event in all_events if str(event.get("id", "")).lower().startswith(str(route_event_id).lower())),
                None,
            )
        if not active_event:
            st.error("Event not found. Showing available events below.")
            # Helpful debug: list available event ids
            try:
                ids = [event["id"] for event in all_events]
                st.info(f"Available event ids: {', '.join(ids)}")
                _debug(f"No active_event for requested id {route_event_id!r}; available ids: {ids}")
            except Exception:
                pass
        else:
            _debug(f"Found active_event: {active_event}")
            if route_info:
                _debug("route_info True: rendering summary view")
                st.markdown(f"## Summary for {active_event['name']}")
                if registrations_collection is None:
                    registrations = list(FALLBACK_REGISTRATIONS.get(active_event["id"], []))
                else:
                    registrations = list_registrations(registrations_collection, active_event["id"])
                _debug(f"Loaded {len(registrations)} registrations for event {active_event['id']}")
                render_info_html(active_event, registrations)
                return
            else:
                st.markdown(f"## RSVP for {active_event['name']}")
                processed = process_attendance_submission(active_event, registrations_collection)
                if processed and st.session_state.get("attendance_success"):
                    st.success(st.session_state.pop("attendance_success"))
                render_attendance_html(active_event)
                return

    # Render home page: create-event section and the events table/list
    with st.container():
        create_event_section(events_collection)

    st.markdown("---")
    st.markdown("## Events")
    if not all_events:
        st.info("No events yet. Create an event to get started.")
    else:
        _debug(f"Rendering events list with {len(all_events)} events")
        header_col1, header_col2, header_col3 = st.columns([4, 2, 1])
        header_col1.markdown("**Event name**")
        header_col2.markdown("**Event ID**")
        header_col3.markdown("**Actions**")

        for event in all_events:
            row_col1, row_col2, row_col3 = st.columns([4, 2, 1])
            event_link = f"/?event={event['id']}"
            info_link = f"/?event={event['id']}&info=true"
            _debug(f"Event row: id={event['id']} name={event['name']} info_link={info_link}")
            primary_style = "display:inline-block;padding:10px 14px;border-radius:8px;background:#2563eb;color:#fff;text-decoration:none;font-weight:600;font-size:16px;"
            secondary_style = "display:inline-block;padding:8px 12px;border-radius:8px;background:#f3f4f6;color:#111;text-decoration:none;font-weight:600;border:1px solid #e5e7eb;"
            row_col1.markdown(f"<a href='{event_link}' style='{primary_style}'>{event['name']}</a>", unsafe_allow_html=True)
            row_col2.markdown(f"`{event['id']}`")
            row_col3.markdown(f"<a href='{info_link}' style='{secondary_style}'>Info</a>", unsafe_allow_html=True)

    # Debug sidebar: show the last debug messages for quick inspection
    try:
        with st.sidebar.expander("Debug logs (latest first)"):
            for msg in reversed(st.session_state.get("_debug_logs", [])[-50:]):
                st.text(msg)
    except Exception:
        pass


if __name__ == "__main__":
    main()

