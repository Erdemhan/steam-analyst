"""Session state management for the UI module.

This module defines the complete, closed set of st.session_state keys
that the ui module is permitted to write to. Constraining session state keys
prevents implicit, ad-hoc accumulation of state and ensures testability.
"""

from typing import Final

SESSION_KEYS: Final[tuple[str, ...]] = ('active_run_id', 'last_event_id', 'event_log')
"""The complete, closed set of st.session_state keys this module is allowed to write.

Attributes:
    active_run_id (str | None): The run currently being watched by the progress panel.
        Set by Start (render_new_analysis_page) and by Resume (render_past_analyses_page);
        not used by render_analysis_detail_page, which addresses its run via
        st.query_params['run_id'] instead, deliberately, so the detail view stays
        refresh-safe and linkable independent of session state.
    last_event_id (int): High-water mark for incremental storage.read_run_events reads.
        Defaults to 0.
    event_log (list[RunEvent]): Accumulated events across polls, needed because
        read_run_events is incremental -- without accumulation, each poll would show
        only its newest slice and the panel's history would appear to reset every 2
        seconds.

No other key may be written to st.session_state by this module. Widget values are
exempt since Streamlit widgets manage their own state by key; the selected run for
the detail page is exempt since it lives in st.query_params, not session_state, by
design.
"""
