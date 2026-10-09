from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("pricing/", views.pricing_view, name="pricing"),
    path("session/new/", views.new_session, name="new_session"),
    path("session/<uuid:session_id>/", views.live_session, name="live_session"),
    path("session/<uuid:session_id>/detail/", views.session_detail, name="session_detail"),
    path("settings/", views.settings_page, name="settings"),
    path("profile/", views.profile_page, name="profile"),
    # API
    path("api/sessions/", views.api_list_sessions, name="api_list_sessions"),
    path("api/session/<uuid:session_id>/activate/", views.api_activate_session, name="api_activate"),
    path("api/session/<uuid:session_id>/end/", views.api_end_session, name="api_end"),
    path("api/session/<uuid:session_id>/transcript/", views.api_transcript, name="api_transcript"),
    path("api/session/<uuid:session_id>/audio-chunk/", views.api_save_audio_chunk, name="api_audio_chunk"),
    path("api/session/<uuid:session_id>/transcribe/", views.api_transcribe, name="api_transcribe"),
    path("api/session/<uuid:session_id>/chat/", views.api_chat, name="api_chat"),
    path("api/session/<uuid:session_id>/data/", views.api_session_data, name="api_data"),
    path("api/session/<uuid:session_id>/delete/", views.api_delete_session, name="api_delete"),
    path("api/session/<uuid:session_id>/edit/", views.api_edit_session, name="api_edit"),
    path("api/session/<uuid:session_id>/export/", views.api_export_session, name="api_export"),
    path("api/session/<uuid:session_id>/note/", views.api_add_note, name="api_note"),
    # Teams Recorder
    path("api/session/<uuid:session_id>/participants/", views.api_meeting_participants, name="api_participants"),
    path("api/session/<uuid:session_id>/participants/<uuid:participant_id>/delete/", views.api_delete_participant, name="api_delete_participant"),
    path("api/session/<uuid:session_id>/entry/<uuid:entry_id>/speaker/", views.api_update_entry_speaker, name="api_entry_speaker"),
    path("api/session/<uuid:session_id>/meeting-summary/", views.api_meeting_summary, name="api_meeting_summary"),
    path("api/build-conversation/", views.api_build_conversation, name="api_build_conversation"),
    path("api/config/", views.api_config, name="api_config"),
    path("api/regenerate-token/", views.api_regenerate_token, name="api_regenerate_token"),
    # Stats
    path("api/stats/", views.api_stats, name="api_stats"),
    # Session scoring
    path("api/session/<uuid:session_id>/score/", views.api_session_score, name="api_session_score"),
    # Billing
    path("billing/checkout/<str:plan>/", views.billing_checkout, name="billing_checkout"),
    path("billing/success/", views.billing_success, name="billing_success"),
    path("billing/portal/", views.billing_portal, name="billing_portal"),
    path("billing/webhook/", views.stripe_webhook, name="stripe_webhook"),
    # Onboarding
    path("onboarding/", views.onboarding_view, name="onboarding"),
    # Desktop overlay auth
    path("api/login/", views.api_login, name="api_login"),
    path("api/session/new/", views.api_new_session, name="api_new_session"),
]
