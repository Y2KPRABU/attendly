import os
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from pymongo.errors import PyMongoError

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


def get_route_selection():
    # Normalize query param keys to be case-insensitive (some hosts may change casing)
    params = {k.lower(): v for k, v in st.query_params.items()}
    event_id = params.get("event", [None])[0]
    info_raw = params.get("info", [""])[0]
    info = str(info_raw).lower() in {"1", "true", "yes"}
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
    st.html(html, unsafe_allow_javascript=True)


def process_attendance_submission(event, registrations_collection):
    params = st.query_params
    if params.get("submit", ["0"])[0] != "1":
        return False

    response = params.get("response", [""])[0]
    main_name = params.get("name", [""])[0].strip()
    adult_count = int(params.get("adult_count", ["0"])[0] or 0)
    child_count = int(params.get("child_count", ["0"])[0] or 0)

    if response not in {"Yes", "No", "Maybe"}:
        st.warning("Please select a valid response.")
        return True

    if response == "No":
        insert_registration(registrations_collection, event["id"], response, "No attendee", 0, 0)
        st.session_state["attendance_success"] = "Your attendance response has been recorded as No."
        return True

    if not main_name:
        st.warning("Please enter the main attendee name.")
        return True

    insert_registration(registrations_collection, event["id"], response, main_name, adult_count, child_count)
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

def create_event_section(events_collection):
    st.markdown("## Create a new event")
    with st.form("create_event_form"):
        event_name = st.text_input("Event name", placeholder="Enter a unique event name")
        create = st.form_submit_button("Create event")
        if create:
            event_name = event_name.strip()
            if not event_name:
                st.warning("Event name cannot be empty.")
            elif find_event_by_name(events_collection, event_name):
                st.warning("An event with that name already exists. Choose a unique name.")
            else:
                insert_event(events_collection, event_name)
                st.success(f"Event '{event_name}' created.")
                st.rerun()


def main():
    init_session_state()
    load_css()

    # Use query params for routing: ?event=<id> and optional &info=true
    route_event_id, route_info = get_route_selection()

    st.title("Attendly")
    st.markdown("Create and manage event RSVPs with mobile-friendly layout.")

    try:
        events_collection = get_events_collection()
        registrations_collection = get_registrations_collection()
    except (PyMongoError, ValueError) as error:
        st.error(f"Could not connect to MongoDB: {error}")
        return

    all_events = list_events(events_collection)

    # If an event is specified in query params, render its view directly.
    if route_event_id:
        # Try direct DB lookup first, then fall back to in-memory list matches.
        try:
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
            except Exception:
                pass
        else:
            if route_info:
                st.markdown(f"## Summary for {active_event['name']}")
                registrations = list_registrations(registrations_collection, active_event["id"])
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
        header_col1, header_col2, header_col3 = st.columns([4, 2, 1])
        header_col1.markdown("**Event name**")
        header_col2.markdown("**Event ID**")
        header_col3.markdown("**Actions**")

        for event in all_events:
            row_col1, row_col2, row_col3 = st.columns([4, 2, 1])
            event_link = f"/?event={event['id']}"
            info_link = f"/?event={event['id']}&info=true"
            primary_style = "display:inline-block;padding:10px 14px;border-radius:8px;background:#2563eb;color:#fff;text-decoration:none;font-weight:600;font-size:16px;"
            secondary_style = "display:inline-block;padding:8px 12px;border-radius:8px;background:#f3f4f6;color:#111;text-decoration:none;font-weight:600;border:1px solid #e5e7eb;"
            row_col1.markdown(f"<a href='{event_link}' style='{primary_style}'>{event['name']}</a>", unsafe_allow_html=True)
            row_col2.markdown(f"`{event['id']}`")
            row_col3.markdown(f"<a href='{info_link}' style='{secondary_style}'>Info</a>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()

