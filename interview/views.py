import json
import os
import uuid
from datetime import timezone

import groq as groq_lib
import openai as openai_lib
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone as dj_timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import NewSessionForm, UserProfileForm
from .models import AIMessage, InterviewSession, MeetingParticipant, TranscriptEntry, UserProfile


def _get_chat_client():
    """Return (client, model, provider) — prefers OpenRouter if key is set, else Groq."""
    if settings.OPENROUTER_API_KEY:
        client = openai_lib.OpenAI(
            api_key=settings.OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
        )
        return client, settings.OPENROUTER_MODEL, "openrouter"
    if settings.GROQ_API_KEY:
        client = openai_lib.OpenAI(
            api_key=settings.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
        )
        return client, settings.GROQ_MODEL, "groq"
    return None, None, None


def login_view(request):
    if request.user.is_authenticated:
        return redirect("/")
    form = AuthenticationForm(request, data=request.POST or None)
    error = None
    if request.method == "POST":
        if form.is_valid():
            login(request, form.get_user())
            return redirect(request.GET.get("next", "/"))
        error = "Invalid username or password."
    return render(request, "interview/login.html", {"form": form, "error": error})


def signup_view(request):
    if request.user.is_authenticated:
        return redirect("/")
    error = None
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("/")
        error = form.errors.as_text()
    else:
        form = UserCreationForm()
    return render(request, "interview/signup.html", {"form": form, "error": error})


def home(request):
    if not request.user.is_authenticated:
        return render(request, "interview/landing.html")
    sessions = InterviewSession.objects.filter(owner=request.user)
    active_count = sessions.filter(status=InterviewSession.STATUS_ACTIVE).count()
    ended_count = sessions.filter(status=InterviewSession.STATUS_ENDED).count()
    return render(request, "interview/home.html", {
        "sessions": sessions,
        "active_count": active_count,
        "ended_count": ended_count,
    })


def pricing_view(request):
    return render(request, "interview/pricing.html")


@login_required
def new_session(request):
    # Pre-fill background from user profile if available
    initial = {}
    if request.user.is_authenticated:
        try:
            initial["extra_context"] = request.user.profile.background
            initial["company"] = request.user.profile.company
        except UserProfile.DoesNotExist:
            pass

    if request.method == "POST":
        form = NewSessionForm(request.POST)
        if form.is_valid():
            session = form.save(commit=False)
            session.owner = request.user
            session.save()
            return redirect("live_session", session_id=session.id)
    else:
        form = NewSessionForm(initial=initial)
    return render(request, "interview/new_session.html", {"form": form})


@login_required
def live_session(request, session_id):
    session = get_object_or_404(InterviewSession, id=session_id, owner=request.user)
    transcripts = session.transcripts.all()
    ai_messages = session.ai_messages.all()
    return render(
        request,
        "interview/live_session.html",
        {"session": session, "transcripts": transcripts, "ai_messages": ai_messages},
    )


@login_required
def session_detail(request, session_id):
    session = get_object_or_404(InterviewSession, id=session_id)
    transcripts = session.transcripts.all()
    ai_messages = session.ai_messages.all()
    return render(
        request,
        "interview/session_detail.html",
        {"session": session, "transcripts": transcripts, "ai_messages": ai_messages},
    )


def _auth_required(request):
    ext_token = request.headers.get('X-Ext-Token', '').strip()
    if ext_token:
        # Accept global env token (backward compat)
        if ext_token == getattr(settings, 'EXT_TOKEN', ''):
            return None
        # Accept any user's personal token
        if UserProfile.objects.filter(ext_token=ext_token).exists():
            return None
    if not request.user.is_authenticated:
        return JsonResponse({"error": "login required"}, status=401)
    return None


def _profile_for_token(token):
    """Return the UserProfile whose ext_token matches, or None."""
    try:
        return UserProfile.objects.get(ext_token=token.strip())
    except UserProfile.DoesNotExist:
        return None


@csrf_exempt
def api_config(request):
    """Return user config by token — lets Electron auto-configure from just the token."""
    ext_token = request.headers.get('X-Ext-Token', '').strip()
    profile = _profile_for_token(ext_token) if ext_token else None
    if not profile:
        # Fall back to session-authenticated user
        if not request.user.is_authenticated:
            return JsonResponse({"error": "invalid token or not logged in"}, status=401)
        profile, _ = UserProfile.objects.get_or_create(user=request.user)

    active_sessions = InterviewSession.objects.filter(
        status=InterviewSession.STATUS_ACTIVE
    ).order_by('-created_at')[:5]
    latest_session = InterviewSession.objects.order_by('-created_at').first()

    return JsonResponse({
        "username": profile.user.username,
        "display_name": profile.display_name or profile.user.username,
        "role": profile.role,
        "company": profile.company,
        "ext_token": profile.ext_token,
        "active_sessions": [
            {"id": str(s.id), "title": s.title, "company": s.company, "status": s.status, "session_type": s.session_type}
            for s in active_sessions
        ],
        "latest_session_id": str(latest_session.id) if latest_session else None,
    })


@csrf_exempt
@require_POST
def api_regenerate_token(request):
    """Regenerate the user's ext_token. Redirects back to profile if browser request."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "login required"}, status=401)
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    profile.regenerate_token()
    # If called from the profile page form, redirect back
    if request.headers.get('Accept', '').find('text/html') >= 0:
        return redirect('profile')
    return JsonResponse({"ext_token": profile.ext_token})


@csrf_exempt
def api_list_sessions(request):
    """List sessions for the extension picker."""
    if (r := _auth_required(request)): return r
    sessions = InterviewSession.objects.order_by('-created_at')[:20]
    return JsonResponse({"sessions": [
        {"id": str(s.id), "title": s.title, "company": s.company, "status": s.status,
         "created_at": s.created_at.isoformat() if s.created_at else None}
        for s in sessions
    ]})


@csrf_exempt
@require_POST
def api_activate_session(request, session_id):
    if (r := _auth_required(request)): return r
    session = get_object_or_404(InterviewSession, id=session_id)
    session.status = InterviewSession.STATUS_ACTIVE
    session.save()
    return JsonResponse({"status": "active", "id": str(session.id)})


@csrf_exempt
@require_POST
def api_end_session(request, session_id):
    if (r := _auth_required(request)): return r
    session = get_object_or_404(InterviewSession, id=session_id)
    session.status = InterviewSession.STATUS_ENDED
    session.ended_at = dj_timezone.now()
    session.save()
    return JsonResponse({"status": "ended"})


@csrf_exempt
@require_POST
def api_transcript(request, session_id):
    if (r := _auth_required(request)): return r
    session = get_object_or_404(InterviewSession, id=session_id)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)

    entries = data.get("transcripts", [])
    created = []
    for entry in entries:
        content = entry.get("content", "").strip()
        if not content:
            continue
        obj = TranscriptEntry.objects.create(
            session=session,
            content=content,
            speaker_type=entry.get("type", TranscriptEntry.TYPE_MIC),
            speaker_name=entry.get("speaker_name", ""),
        )
        created.append({"id": str(obj.id), "content": obj.content})

    return JsonResponse({"saved": len(created), "entries": created})


@csrf_exempt
def api_chat(request, session_id):
    """Stream Claude's answer as Server-Sent Events."""
    if (r := _auth_required(request)): return r
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    session = get_object_or_404(InterviewSession, id=session_id)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)

    question = data.get("question", "").strip()
    if not question:
        return JsonResponse({"error": "question required"}, status=400)

    client, model, provider = _get_chat_client()
    if not client:
        return JsonResponse(
            {"error": "No AI key set. Add OPENROUTER_API_KEY or GROQ_API_KEY to your environment."},
            status=500,
        )

    recent_transcripts = session.transcripts.order_by("-created_at")[:30]
    def _fmt_entry(e):
        label = e.speaker_name if e.speaker_name else e.speaker_type
        return f"[{label}]: {e.content}"
    transcript_text = "\n".join(_fmt_entry(e) for e in reversed(list(recent_transcripts)))

    system_prompt = _build_system_prompt(session)
    user_message = f"Recent conversation transcript:\n{transcript_text}\n\nQuestion/topic to address: {question}"

    def stream_sse():
        full_content = []
        yield f"data: {json.dumps({'type': 'start'})}\n\n"
        try:
            stream = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=600,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    full_content.append(delta)
                    yield f"data: {json.dumps({'type': 'text', 'text': delta})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"
            return

        saved_content = "".join(full_content)
        AIMessage.objects.create(
            session=session,
            trigger_text=question,
            content=saved_content,
        )
        yield f"data: {json.dumps({'type': 'end'})}\n\n"

    response = StreamingHttpResponse(stream_sse(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@csrf_exempt
@require_POST
def api_transcribe(request, session_id):
    """Transcribe an audio chunk using Groq Whisper and save it."""
    if (r := _auth_required(request)): return r
    session = get_object_or_404(InterviewSession, id=session_id)
    api_key = settings.GROQ_API_KEY
    if not api_key:
        return JsonResponse({"error": "GROQ_API_KEY not set"}, status=500)

    audio_file = request.FILES.get("audio")
    if not audio_file:
        return JsonResponse({"error": "no audio file"}, status=400)

    speaker_hint = request.POST.get("speaker", TranscriptEntry.TYPE_MIC)
    model = settings.GROQ_WHISPER_MODEL

    try:
        client = groq_lib.Groq(api_key=api_key)
        raw = audio_file.read()
        transcription = client.audio.transcriptions.create(
            file=(audio_file.name or "audio.webm", raw, audio_file.content_type or "audio/webm"),
            model=model,
            response_format="text",
        )
        text = transcription.strip() if isinstance(transcription, str) else transcription.text.strip()
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=500)

    # Whisper hallucinations on silence/noise — discard them
    _HALLUCINATIONS = {
        "thank you.", "thank you", "thanks.", "thanks",
        "you.", ".", "..", "...", "bye.", "bye",
        "you're welcome.", "you're welcome",
        "subscribe.", "subscribe",
    }
    if not text or text.lower().strip() in _HALLUCINATIONS:
        return JsonResponse({"text": ""})

    speaker = speaker_hint if speaker_hint in (TranscriptEntry.TYPE_MIC, TranscriptEntry.TYPE_SYSTEM) else TranscriptEntry.TYPE_MIC
    speaker_name = request.POST.get("speaker_name", "")

    entry = TranscriptEntry.objects.create(
        session=session,
        content=text,
        speaker_type=speaker,
        speaker_name=speaker_name,
    )
    return JsonResponse({"text": text, "id": str(entry.id), "speaker": speaker, "speaker_name": speaker_name})


@csrf_exempt
def api_session_data(request, session_id):
    """Return recent transcripts and AI messages as JSON (used for polling)."""
    if (r := _auth_required(request)): return r
    session = get_object_or_404(InterviewSession, id=session_id)
    since_id = request.GET.get("since_transcript_id")

    transcripts_qs = session.transcripts.order_by("created_at")
    if since_id:
        from django.db.models import Q
        try:
            since = TranscriptEntry.objects.get(id=since_id, session=session)
            transcripts_qs = transcripts_qs.filter(created_at__gt=since.created_at)
        except TranscriptEntry.DoesNotExist:
            pass

    transcripts = [
        {"id": str(t.id), "content": t.content, "speaker_type": t.speaker_type, "speaker_name": t.speaker_name}
        for t in transcripts_qs
    ]
    ai_messages = [
        {"id": str(m.id), "content": m.content, "trigger": m.trigger_text}
        for m in session.ai_messages.order_by("-created_at")[:5]
    ]
    has_past_meetings = False
    if session.session_type == InterviewSession.SESSION_TYPE_MEETING and session.company:
        has_past_meetings = InterviewSession.objects.filter(
            company__iexact=session.company,
            session_type=InterviewSession.SESSION_TYPE_MEETING,
            status=InterviewSession.STATUS_ENDED,
        ).exclude(id=session.id).exists()

    return JsonResponse({
        "title": session.title,
        "status": session.status,
        "transcripts": transcripts,
        "ai_messages": ai_messages,
        "has_past_meetings": has_past_meetings,
    })


@csrf_exempt
def api_delete_session(request, session_id):
    if (r := _auth_required(request)): return r
    if request.method != "DELETE":
        return JsonResponse({"error": "DELETE required"}, status=405)
    session = get_object_or_404(InterviewSession, id=session_id)
    session.delete()
    return JsonResponse({"ok": True})


@csrf_exempt
@require_POST
def api_edit_session(request, session_id):
    if (r := _auth_required(request)): return r
    session = get_object_or_404(InterviewSession, id=session_id)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)
    title = data.get("title", "").strip()
    if not title:
        return JsonResponse({"error": "title required"}, status=400)
    session.title = title
    session.company = data.get("company", session.company)
    session.save()
    return JsonResponse({"ok": True, "title": session.title, "company": session.company})


@csrf_exempt
def api_export_session(request, session_id):
    if (r := _auth_required(request)): return r
    session = get_object_or_404(InterviewSession, id=session_id)
    fmt = request.GET.get("fmt", "txt")
    transcripts = session.transcripts.order_by("created_at")
    ai_messages = session.ai_messages.order_by("created_at")

    if fmt == "md":
        lines = [f"# {session.title}", ""]
        if session.company:
            lines.append(f"**Company:** {session.company}")
        lines.append(f"**Date:** {session.created_at.strftime('%B %d, %Y %I:%M %p')}")
        lines.append(f"**Status:** {session.status}")
        if session.ended_at:
            lines.append(f"**Ended:** {session.ended_at.strftime('%I:%M %p')}")
        lines.append("")
        if session.job_description:
            lines += ["## Job Description", "", session.job_description, ""]
        if session.extra_context:
            lines += ["## Background", "", session.extra_context, ""]
        if transcripts.exists():
            lines += ["## Transcript", ""]
            for t in transcripts:
                lines.append(f"**[{t.speaker_type.upper()}]** _{t.created_at.strftime('%I:%M:%S %p')}_")
                lines.append(t.content)
                lines.append("")
        if ai_messages.exists():
            lines += ["## AI Answers", ""]
            for m in ai_messages:
                if m.trigger_text:
                    lines.append(f"**Q:** {m.trigger_text}")
                lines.append(m.content)
                lines.append("")
        content = "\n".join(lines)
        content_type = "text/markdown"
        filename = f"{session.title.lower().replace(' ', '_')}_session.md"
    else:
        lines = [f"SESSION: {session.title}", "=" * 50, ""]
        if session.company:
            lines.append(f"Company: {session.company}")
        lines.append(f"Date: {session.created_at.strftime('%B %d, %Y %I:%M %p')}")
        lines.append(f"Status: {session.status}")
        lines.append("")
        if session.job_description:
            lines += ["JOB DESCRIPTION:", "-" * 30, session.job_description, ""]
        if session.extra_context:
            lines += ["BACKGROUND:", "-" * 30, session.extra_context, ""]
        if transcripts.exists():
            lines += ["TRANSCRIPT:", "-" * 30]
            for t in transcripts:
                lines.append(f"[{t.speaker_type.upper()}] {t.created_at.strftime('%I:%M:%S %p')}")
                lines.append(t.content)
                lines.append("")
        if ai_messages.exists():
            lines += ["AI ANSWERS:", "-" * 30]
            for m in ai_messages:
                if m.trigger_text:
                    lines.append(f"Q: {m.trigger_text}")
                lines.append(m.content)
                lines.append("")
        content = "\n".join(lines)
        content_type = "text/plain"
        filename = f"{session.title.lower().replace(' ', '_')}_session.txt"

    response = HttpResponse(content, content_type=f"{content_type}; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@csrf_exempt
@require_POST
def api_add_note(request, session_id):
    if (r := _auth_required(request)): return r
    session = get_object_or_404(InterviewSession, id=session_id)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)
    content = data.get("content", "").strip()
    if not content:
        return JsonResponse({"error": "content required"}, status=400)
    entry = TranscriptEntry.objects.create(
        session=session,
        content=content,
        speaker_type=TranscriptEntry.TYPE_SYSTEM,
    )
    return JsonResponse({"ok": True, "id": str(entry.id), "content": entry.content})


# ── TEAMS RECORDER ────────────────────────────────────────────────────────────

@csrf_exempt
def api_meeting_participants(request, session_id):
    """GET list of participants / POST to add one."""
    if (r := _auth_required(request)): return r
    session = get_object_or_404(InterviewSession, id=session_id)

    if request.method == "GET":
        ps = [
            {"id": str(p.id), "name": p.name, "role": p.role, "color": p.color}
            for p in session.participants.all()
        ]
        return JsonResponse({"participants": ps})

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)

    name = data.get("name", "").strip()
    if not name:
        return JsonResponse({"error": "name required"}, status=400)

    # Pick next color automatically
    used_colors = list(session.participants.values_list("color", flat=True))
    palette = MeetingParticipant.COLORS
    color = data.get("color") or next((c for c in palette if c not in used_colors), palette[0])

    p, created = MeetingParticipant.objects.get_or_create(
        session=session, name=name,
        defaults={"role": data.get("role", ""), "color": color},
    )
    return JsonResponse({"id": str(p.id), "name": p.name, "role": p.role, "color": p.color, "created": created})


@csrf_exempt
@require_POST
def api_delete_participant(request, session_id, participant_id):
    if (r := _auth_required(request)): return r
    p = get_object_or_404(MeetingParticipant, id=participant_id, session__id=session_id)
    p.delete()
    return JsonResponse({"ok": True})


@csrf_exempt
@require_POST
def api_update_entry_speaker(request, session_id, entry_id):
    """Assign a speaker_name to a transcript entry."""
    if (r := _auth_required(request)): return r
    entry = get_object_or_404(TranscriptEntry, id=entry_id, session__id=session_id)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)
    entry.speaker_name = data.get("speaker_name", "")
    entry.save(update_fields=["speaker_name"])
    return JsonResponse({"ok": True, "speaker_name": entry.speaker_name})


@csrf_exempt
@require_POST
def api_meeting_summary(request, session_id):
    """Generate AI meeting summary with action items, decisions, and open questions."""
    if (r := _auth_required(request)): return r
    session = get_object_or_404(InterviewSession, id=session_id)
    client, model, provider = _get_chat_client()
    if not client:
        return JsonResponse({"error": "No AI key set. Add OPENROUTER_API_KEY or GROQ_API_KEY."}, status=500)

    transcripts = session.transcripts.order_by("created_at")
    if not transcripts.exists():
        return JsonResponse({"error": "No transcript to summarize"}, status=400)

    def _fmt(e):
        label = e.speaker_name if e.speaker_name else e.speaker_type
        return f"[{label}]: {e.content}"

    transcript_text = "\n".join(_fmt(e) for e in transcripts)

    participants = session.participants.all()
    participant_list = ", ".join(p.name for p in participants) if participants.exists() else "unknown"

    system_msg = (
        "You are an expert meeting analyst. Generate a structured meeting summary. "
        "Return ONLY valid JSON, no markdown, in this exact format:\n"
        '{"summary": "2-3 sentence overview", '
        '"key_decisions": ["decision 1", ...], '
        '"action_items": [{"item": "...", "owner": "...", "deadline": "..."}, ...], '
        '"open_questions": ["question 1", ...], '
        '"information_gaps": ["gap 1", ...]}'
    )
    user_msg = (
        f"Meeting: {session.title}\n"
        f"Participants: {participant_list}\n"
        f"Agenda: {session.meeting_agenda or session.job_description or 'not specified'}\n\n"
        f"Full transcript:\n{transcript_text[:4000]}"
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}],
            max_tokens=1200,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
            if raw.endswith("```"):
                raw = raw[:-3]
        result = json.loads(raw)
        AIMessage.objects.create(
            session=session,
            trigger_text="[Meeting Summary]",
            content=json.dumps(result),
        )
        return JsonResponse(result)
    except json.JSONDecodeError:
        return JsonResponse({"error": "AI returned invalid JSON"}, status=500)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=500)


@csrf_exempt
@require_POST
def api_build_conversation(request):
    """Generate a structured conversation blueprint via Groq."""
    if (r := _auth_required(request)): return r
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)

    title = data.get("title", "").strip()
    company = data.get("company", "").strip()
    jd = data.get("jd", "").strip()
    background = data.get("background", "").strip()

    if not title:
        return JsonResponse({"error": "title required"}, status=400)

    client, model, provider = _get_chat_client()
    if not client:
        return JsonResponse({"error": "No AI key set. Add OPENROUTER_API_KEY or GROQ_API_KEY."}, status=500)

    context_block = f"Role: {title}"
    if company:
        context_block += f"\nCompany: {company}"
    if jd:
        context_block += f"\nJob/Meeting Context:\n{jd[:1200]}"
    if background:
        context_block += f"\nSpeaker Background:\n{background[:600]}"

    prompt = f"""You are an expert meeting coach helping a professional prepare for a high-stakes conversation.

{context_block}

Generate a structured 6-phase conversation blueprint. Return ONLY a valid JSON object — no markdown, no explanation — in this exact format:
{{
  "phases": [
    {{
      "icon": "🎯",
      "phase": "Opening",
      "subtitle": "First 2 minutes",
      "points": ["Specific point 1", "Specific point 2", "Specific point 3"]
    }}
  ]
}}

Use these 6 phases in order:
1. icon 🎯 — "Opening" — subtitle "First 2 min"
2. icon 🏗️ — "Context & Framing" — subtitle "Set the stage"
3. icon 💡 — "Core Discussion" — subtitle "Main agenda"
4. icon 🔧 — "Technical Depth" — subtitle "Go deeper"
5. icon ❓ — "Questions to Ask" — subtitle "Your turn"
6. icon 🤝 — "Close & Next Steps" — subtitle "End strong"

Make every bullet point HIGHLY specific to the role, company, and context provided. Reference actual technologies, responsibilities, and topics mentioned. Be sharp, concise, and actionable. 3-4 points per phase."""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1400,
        )
        raw = response.choices[0].message.content.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        return JsonResponse(result)
    except json.JSONDecodeError:
        return JsonResponse({"error": "AI returned invalid JSON — try again"}, status=500)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=500)


@login_required
def profile_page(request):

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    # Auto-generate a token for new profiles that don't have one yet
    if not profile.ext_token:
        profile.regenerate_token()
    msg = None

    if request.method == "POST":
        form = UserProfileForm(request.POST, instance=profile, user=request.user)
        if form.is_valid():
            form.save_user(request.user)
            form.save()
            msg = ("success", "Profile saved.")
        else:
            msg = ("error", "Please fix the errors below.")
    else:
        form = UserProfileForm(instance=profile, user=request.user)

    from .models import TranscriptEntry as TE, AIMessage as AI
    session_count = InterviewSession.objects.count()
    transcript_count = TE.objects.count()
    ai_count = AI.objects.count()

    return render(request, "interview/profile.html", {
        "form": form,
        "profile": profile,
        "msg": msg,
        "session_count": session_count,
        "transcript_count": transcript_count,
        "ai_count": ai_count,
    })


@login_required
def settings_page(request):
    msg = None
    if request.method == "POST":
        api_key = request.POST.get("api_key", "").strip()
        model = request.POST.get("model", "").strip()
        whisper_model = request.POST.get("whisper_model", "").strip()
        openrouter_key = request.POST.get("openrouter_key", "").strip()
        openrouter_model = request.POST.get("openrouter_model", "").strip()
        env_path = os.path.join(settings.BASE_DIR, ".env")
        try:
            if os.path.exists(env_path):
                with open(env_path, "r") as f:
                    lines = f.readlines()
            else:
                lines = []
            env_dict = {}
            for line in lines:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env_dict[k.strip()] = v.strip()
            if api_key:
                env_dict["GROQ_API_KEY"] = api_key
            if model:
                env_dict["GROQ_MODEL"] = model
            if whisper_model:
                env_dict["GROQ_WHISPER_MODEL"] = whisper_model
            if openrouter_key:
                env_dict["OPENROUTER_API_KEY"] = openrouter_key
            if openrouter_model:
                env_dict["OPENROUTER_MODEL"] = openrouter_model
            with open(env_path, "w") as f:
                for k, v in env_dict.items():
                    f.write(f"{k}={v}\n")
            msg = ("success", "Settings saved. Restart the server for changes to take effect.")
        except Exception as exc:
            msg = ("error", f"Failed to save: {exc}")

    current = {
        "api_key": settings.GROQ_API_KEY or "",
        "model": settings.GROQ_MODEL or "",
        "whisper_model": settings.GROQ_WHISPER_MODEL or "",
        "openrouter_key": settings.OPENROUTER_API_KEY or "",
        "openrouter_model": settings.OPENROUTER_MODEL or "",
    }
    return render(request, "interview/settings.html", {"current": current, "msg": msg})


def _build_system_prompt(session: InterviewSession) -> str:
    if session.session_type == InterviewSession.SESSION_TYPE_MEETING:
        parts = [
            "You are an expert meeting assistant and strategic advisor helping a professional during a live Teams meeting.",
            "Your job is to provide real-time suggestions, identify information gaps, extract action items, and help the user ask the right questions.",
            "Be concise, actionable, and specific to the meeting context.",
            "When asked for questions to ask, suggest 2-3 targeted, insightful questions based on what has been discussed.",
            "When asked for action items, list them clearly with owner/deadline format where possible.",
            "Keep responses under 250 words unless generating a full meeting summary.",
            "",
        ]
        if session.title:
            parts.append(f"Meeting: {session.title}")
        if session.company:
            parts.append(f"Organization: {session.company}")
        if session.meeting_agenda:
            parts.append(f"\nMeeting agenda:\n{session.meeting_agenda[:800]}")
        if session.job_description:
            parts.append(f"\nMeeting context / background:\n{session.job_description[:1000]}")
        if session.extra_context:
            parts.append(f"\nUser's background / role:\n{session.extra_context[:1500]}")
        # Include participant list
        participants = session.participants.all()
        if participants.exists():
            names = ", ".join(p.name + (f" ({p.role})" if p.role else "") for p in participants)
            parts.append(f"\nMeeting participants: {names}")
        # Include cross-session context from past meetings with same company
        if session.company:
            past = InterviewSession.objects.filter(
                company__iexact=session.company,
                session_type=InterviewSession.SESSION_TYPE_MEETING,
                status=InterviewSession.STATUS_ENDED,
            ).exclude(id=session.id).order_by("-created_at")[:3]
            if past.exists():
                ctx_lines = ["\nContext from previous meetings with this organization:"]
                for ps in past:
                    recent = ps.transcripts.order_by("-created_at")[:10]
                    summary = " | ".join(t.content[:80] for t in reversed(list(recent)))
                    ctx_lines.append(f"- {ps.title} ({ps.created_at.strftime('%b %d, %Y')}): {summary[:300]}")
                parts.extend(ctx_lines)
    else:
        parts = [
            "You are an expert interview coach and assistant helping a candidate answer interview questions in real time.",
            "Provide concise, structured, confident answers.",
            "Use bullet points or the STAR method (Situation, Task, Action, Result) when appropriate.",
            "Keep answers under 200 words unless the question requires more depth.",
            "",
        ]
        if session.title:
            parts.append(f"Role being interviewed for: {session.title}")
        if session.company:
            parts.append(f"Company: {session.company}")
        if session.job_description:
            parts.append(f"\nJob description:\n{session.job_description[:1000]}")
        if session.extra_context:
            parts.append(f"\nCandidate background / resume:\n{session.extra_context[:2000]}")
    return "\n".join(parts)
