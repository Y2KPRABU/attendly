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
)

st.set_page_config(page_title="Attendly", page_icon="🎉", layout="wide")

SESSION_SELECTED_EVENT = "selected_event_id"
SESSION_INFO_EVENT = "info_event_id"


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
    return None, False


def push_route(event_id: str, info: bool = False):
    route = f"/event/{event_id}"
    if info:
        route += "/info"
    components.html(
        f"<script>window.history.replaceState(null, '', '{route}');</script>",
        height=0,
    )


def clear_route():
    components.html(
        "<script>window.history.replaceState(null, '', '/');</script>",
        height=0,
    )


def sync_route_from_path():
    components.html(
        """
        <script>
        const path = window.location.pathname;
        const match = path.match(/^\/event\/([^\/]+)(\/info)?\/?$/);
        if (match) {
            const eventId = match[1];
            const info = !!match[2];
            const route = '/event/' + eventId + (info ? '/info' : '');
            window.history.replaceState(null, '', route);
        }
        </script>
        """,
        height=0,
    )


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
                clear_route()
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

    st.title("Attendly")
    st.markdown("Create and manage event RSVPs with mobile-friendly layout.")

    try:
        events_collection = get_events_collection()
        registrations_collection = get_registrations_collection()
    except (PyMongoError, ValueError) as error:
        st.error(f"Could not connect to MongoDB: {error}")
        return

    with st.container():
        create_event_section(events_collection)

    st.markdown("---")

    st.markdown("## Events")
    all_events = list_events(events_collection)
    if not all_events:
        st.info("No events yet. Create an event to get started.")
    else:
        header_col1, header_col2, header_col3 = st.columns([4, 2, 1])
        header_col1.markdown("**Event name**")
        header_col2.markdown("**Event ID**")
        header_col3.markdown("**Actions**")

        for event in all_events:
            row_col1, row_col2, row_col3 = st.columns([4, 2, 1])
            if row_col1.button(event["name"], key=f"open_{event['id']}"):
                st.session_state[SESSION_SELECTED_EVENT] = event["id"]
                st.session_state[SESSION_INFO_EVENT] = None
                push_route(event["id"])
            row_col2.markdown(f"`{event['id']}`")
            if row_col3.button("Info", key=f"info_{event['id']}"):
                st.session_state[SESSION_INFO_EVENT] = event["id"]
                push_route(event["id"], info=True)

    st.markdown("---")
    selected_id = st.session_state[SESSION_SELECTED_EVENT]
    info_id = st.session_state[SESSION_INFO_EVENT]

    if selected_id:
        active_event = next((event for event in all_events if event["id"] == selected_id), None)
        if active_event:
            render_event_action(active_event, registrations_collection)

    if info_id:
        info_event = next((event for event in all_events if event["id"] == info_id), None)
        if info_event:
            registrations = list_registrations(registrations_collection, info_event["id"])
            with st.expander(f"Summary for {info_event['name']} ({info_event['id']})", expanded=True):
                render_event_info(info_event, registrations)


if __name__ == "__main__":
    main()

