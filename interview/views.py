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
from django.contrib.auth.models import User
from django.contrib import messages
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone as dj_timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import NewSessionForm, UserProfileForm
from .models import AIMessage, InterviewSession, MeetingParticipant, TranscriptEntry, UserProfile, PromptTemplate

AI_HELP_DEFAULTS = [
    {"name": "Default", "icon": "✨", "description": "Clear, direct answer — no forced structure", "prompt": "", "order": 0},
    {"name": "Bullet Points", "icon": "•", "description": "Key points as a concise bulleted list", "prompt": "Respond with a clear heading then 4–7 concise bullet points. No long paragraphs.", "order": 1},
    {"name": "STAR Method", "icon": "⭐", "description": "Situation · Task · Action · Result (interview format)", "prompt": "Structure your answer using the STAR method with four labeled sections: **Situation**, **Task**, **Action**, **Result**. Keep each section concise.", "order": 2},
    {"name": "Technical", "icon": "⌨", "description": "Code examples + explanation + trade-offs", "prompt": "Give a technical answer: include code examples where relevant, explain the mechanism, and list trade-offs or alternatives.", "order": 3},
    {"name": "Summary First", "icon": "📋", "description": "TL;DR headline, then detail", "prompt": "Start with a bold one-sentence TL;DR summary. Then expand with detail in 2–3 short paragraphs.", "order": 4},
    {"name": "Simple / ELI5", "icon": "🧸", "description": "Plain language, no jargon, analogy-driven", "prompt": "Explain in simple, plain language as if to someone new to the topic. Use an analogy. Avoid jargon.", "order": 5},
    {"name": "Comparison", "icon": "⚖", "description": "Pros & cons table or two-column breakdown", "prompt": "Present the answer as a comparison: use a markdown table or two clear sections (pros vs cons, A vs B) and end with a recommendation.", "order": 6},
    {"name": "Step by Step", "icon": "🪜", "description": "Numbered sequential process", "prompt": "Answer as a numbered step-by-step guide. Be specific and actionable at each step.", "order": 7},
]

MEETING_AI_DEFAULTS = [
    {"name": "Action Items", "icon": "📌", "description": "List action items with owners and deadlines", "prompt": "List action items from this meeting so far with owners and deadlines.", "order": 0},
    {"name": "Info Gaps", "icon": "❓", "description": "Key information gaps or unanswered questions", "prompt": "What are the key information gaps or unanswered questions in this meeting?", "order": 1},
    {"name": "Questions to Ask", "icon": "💬", "description": "Top 3 questions to ask right now", "prompt": "What are the top 3 questions I should ask right now given the current discussion?", "order": 2},
    {"name": "Decisions", "icon": "✅", "description": "Key decisions made so far", "prompt": "What key decisions have been made so far in this meeting?", "order": 3},
    {"name": "Status Update", "icon": "📊", "description": "Current status of the meeting", "prompt": "What is the current status of this meeting? What topics have been covered and what is remaining?", "order": 4},
    {"name": "Risks", "icon": "⚠️", "description": "Key risks and concerns raised", "prompt": "Summarize the key risks and concerns raised in this meeting.", "order": 5},
    {"name": "Follow-up Email", "icon": "✉️", "description": "Draft a follow-up email", "prompt": "Draft a follow-up email based on this meeting discussion.", "order": 6},
]


def _seed_default_templates(user):
    if PromptTemplate.objects.filter(owner=user).exists():
        return
    for tpl in AI_HELP_DEFAULTS:
        PromptTemplate.objects.create(owner=user, template_type="ai_help", is_active=True, **tpl)
    for tpl in MEETING_AI_DEFAULTS:
        PromptTemplate.objects.create(owner=user, template_type="meeting_ai", is_active=True, **tpl)


def _check_session_limit(user):
    """Return (ok, sessions_used, limit). ok=False means limit reached."""
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        return True, 0, None
    limit = profile.session_limit
    if limit is None:
        return True, 0, None
    used = InterviewSession.objects.filter(owner=user).count()
    return used < limit, used, limit


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
            _seed_default_templates(user)
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

    ok, sessions_used, limit = _check_session_limit(request.user)
    if not ok:
        return render(request, "interview/new_session.html", {
            "form": NewSessionForm(initial=initial),
            "session_limit_reached": True,
            "sessions_used": sessions_used,
            "session_limit": limit,
        })

    if request.method == "POST":
        form = NewSessionForm(request.POST)
        if form.is_valid():
            session = form.save(commit=False)
            session.owner = request.user
            session.save()
            return redirect("live_session", session_id=session.id)
    else:
        form = NewSessionForm(initial=initial)
    return render(request, "interview/new_session.html", {"form": form, "sessions_used": sessions_used, "session_limit": limit})


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
    session = get_object_or_404(InterviewSession, id=session_id, owner=request.user)
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
        status=InterviewSession.STATUS_ACTIVE,
        owner=profile.user,
    ).order_by('-created_at')[:5]
    latest_session = InterviewSession.objects.filter(
        owner=profile.user,
    ).order_by('-created_at').first()

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
    ext_token = request.headers.get('X-Ext-Token', '').strip()
    profile = _profile_for_token(ext_token) if ext_token else None
    user = profile.user if profile else request.user
    sessions = InterviewSession.objects.filter(owner=user).order_by('-created_at')[:20]
    return JsonResponse({"sessions": [
        {"id": str(s.id), "title": s.title, "company": s.company, "status": s.status,
         "created_at": s.created_at.isoformat() if s.created_at else None}
        for s in sessions
    ]})


@csrf_exempt
@require_POST
def api_activate_session(request, session_id):
    if (r := _auth_required(request)): return r
    ext_token = request.headers.get('X-Ext-Token', '').strip()
    profile = _profile_for_token(ext_token) if ext_token else None
    user = profile.user if profile else request.user
    session = get_object_or_404(InterviewSession, id=session_id, owner=user)
    session.status = InterviewSession.STATUS_ACTIVE
    session.save()
    return JsonResponse({"status": "active", "id": str(session.id)})


@csrf_exempt
@require_POST
def api_end_session(request, session_id):
    if (r := _auth_required(request)): return r
    ext_token = request.headers.get('X-Ext-Token', '').strip()
    profile = _profile_for_token(ext_token) if ext_token else None
    user = profile.user if profile else request.user
    session = get_object_or_404(InterviewSession, id=session_id, owner=user)
    session.status = InterviewSession.STATUS_ENDED
    session.ended_at = dj_timezone.now()
    session.save()
    # Trigger async backup to MySQL if configured
    if getattr(settings, "MYSQL_BACKUP_ENABLED", False):
        import threading
        def _async_backup():
            try:
                from interview.db_sync import backup_to_mysql
                backup_to_mysql(triggered_by="session_end")
            except Exception:
                pass
        threading.Thread(target=_async_backup, daemon=True).start()
    return JsonResponse({"status": "ended"})


@csrf_exempt
@require_POST
def api_transcript(request, session_id):
    if (r := _auth_required(request)): return r
    ext_token = request.headers.get('X-Ext-Token', '').strip()
    profile = _profile_for_token(ext_token) if ext_token else None
    user = profile.user if profile else request.user
    session = get_object_or_404(InterviewSession, id=session_id, owner=user)
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
@require_POST
def api_save_audio_chunk(request, session_id):
    """Save a raw audio chunk from MediaRecorder for the session recording."""
    if (r := _auth_required(request)): return r
    ext_token = request.headers.get('X-Ext-Token', '').strip()
    profile = _profile_for_token(ext_token) if ext_token else None
    user = profile.user if profile else request.user
    session = get_object_or_404(InterviewSession, id=session_id, owner=user)

    audio_data = request.body
    if not audio_data:
        return JsonResponse({"error": "no audio data"}, status=400)

    seq = request.GET.get('seq') or request.headers.get('X-Chunk-Seq', '0')
    try:
        seq = int(seq)
    except (ValueError, TypeError):
        seq = 0

    recordings_dir = settings.BASE_DIR / 'recordings'
    recordings_dir.mkdir(exist_ok=True)
    # Each session gets a subdirectory; chunks are numbered files
    session_dir = recordings_dir / str(session_id)
    session_dir.mkdir(exist_ok=True)
    chunk_path = session_dir / f'{seq:04d}.webm'

    with open(chunk_path, 'wb') as f:
        f.write(audio_data)

    return JsonResponse({"ok": True, "seq": seq, "bytes": len(audio_data)})


_DEFAULT_PREP_NOTES = """\
## Interview Preparation Tips

### STAR Method (Behavioral Questions)
Use this structure for any "Tell me about a time when..." question:
- **Situation**: Set the context briefly (1-2 sentences)
- **Task**: What was your specific responsibility?
- **Action**: What did YOU do? (use "I", not "we") — be specific about your steps
- **Result**: Quantify the outcome (%, $, time saved, team size)

### Key Question Types
- **Behavioral**: "Tell me about a time when you..."
- **Technical**: System design, coding, architecture deep-dives
- **Situational**: "What would you do if..." — show judgment and process
- **Culture fit**: Values alignment, collaboration style, growth mindset

### During the Interview
- Listen fully before answering — it's OK to pause 5-10 seconds to think
- Ask clarifying questions upfront for ambiguous problems
- Think out loud so the interviewer follows your reasoning
- Use concrete numbers and metrics in every answer
- Tailor your examples to match the job description keywords

### Common Mistakes to Avoid
- Don't bad-mouth previous employers or managers
- Don't say your weakness is "I work too hard"
- Don't ramble — aim for 90-second answers unless asked for more
- Don't forget to prepare 2-3 questions to ask them at the end

### My Talking Points
(Edit this section with specific examples from your experience)
- Leadership example:
- Challenge I overcame:
- Technical achievement:
- Why this company / role:
"""

_CONV_HELPER_PROMPT = """You are a real-time conversation analyst embedded in an interview or meeting assistant.

Given the transcript entries below, do exactly two things:

1. LABEL each entry with one tag on its own line:
   [❓ Q]  — a question being asked
   [💡 P]  — a new point / fact being stated
   [🔁 R]  — a repeat or restatement of a previous point (same concept, even different words)
   [✅ T]  — a takeaway, conclusion, or commitment

2. After ALL labels, write a CONTEXT block (3 lines max):
   TONE: (one adjective, e.g. collaborative / curious / tense / defensive / exploratory)
   DYNAMIC: (who is driving the conversation and what pressure or motive is present — one sentence)
   KEY: (the single most important fact, demand, or reveal — one sentence)

Format:
[1] [❓ Q] brief rephrasing of the entry
[2] [💡 P] brief rephrasing
...

TONE: ...
DYNAMIC: ...
KEY: ...

Be precise and brutally concise. No filler. No disclaimers."""


@csrf_exempt
def api_conversation_helper(request, session_id):
    """Analyze the conversation transcript: label entries and extract context."""
    if (r := _auth_required(request)): return r
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    ext_token = request.headers.get('X-Ext-Token', '').strip()
    profile = _profile_for_token(ext_token) if ext_token else None
    user = profile.user if profile else request.user
    session = get_object_or_404(InterviewSession, id=session_id, owner=user)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)

    entries = data.get("entries", [])
    insight_prompt = data.get("insight_prompt", "")

    if not entries:
        # Fall back to the last 20 transcript entries from DB
        recent = session.transcripts.order_by("-created_at")[:20]
        entries = [
            {"speaker": {"microphone": "You", "system": "Them"}.get(e.speaker_type, e.speaker_type),
             "text": e.content}
            for e in reversed(list(recent))
        ]

    if not entries:
        return JsonResponse({"error": "no transcript entries yet"}, status=400)

    client, model, provider = _get_chat_client()
    if not client:
        return JsonResponse(
            {"error": "No AI key set. Add OPENROUTER_API_KEY or GROQ_API_KEY."},
            status=500,
        )

    lines = "\n".join(
        f"[{i+1}] {e.get('speaker','?')}: {e.get('text','')}"
        for i, e in enumerate(entries)
    )
    user_msg = f"Transcript entries to analyze:\n{lines}"
    system_prompt = insight_prompt if insight_prompt else _CONV_HELPER_PROMPT

    def stream_sse():
        yield f"data: {json.dumps({'type': 'start'})}\n\n"
        saved_content = []
        try:
            stream = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=500,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    saved_content.append(delta)
                    yield f"data: {json.dumps({'type': 'text', 'text': delta})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
        if saved_content:
            AIMessage.objects.create(
                session=session,
                trigger_text=insight_prompt or "conversation_helper",
                content="".join(saved_content),
            )
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingHttpResponse(
        stream_sse(),
        content_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@csrf_exempt
def api_chat(request, session_id):
    """Stream Claude's answer as Server-Sent Events."""
    if (r := _auth_required(request)): return r
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    ext_token = request.headers.get('X-Ext-Token', '').strip()
    profile = _profile_for_token(ext_token) if ext_token else None
    user = profile.user if profile else request.user
    session = get_object_or_404(InterviewSession, id=session_id, owner=user)

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
        _type_label = {'microphone': 'You', 'system': 'Interviewer', 'note': 'Note'}.get(e.speaker_type, e.speaker_type)
        label = e.speaker_name if e.speaker_name else _type_label
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
    ext_token = request.headers.get('X-Ext-Token', '').strip()
    profile = _profile_for_token(ext_token) if ext_token else None
    user = profile.user if profile else request.user
    session = get_object_or_404(InterviewSession, id=session_id, owner=user)
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
    ext_token = request.headers.get('X-Ext-Token', '').strip()
    profile = _profile_for_token(ext_token) if ext_token else None
    user = profile.user if profile else request.user
    session = get_object_or_404(InterviewSession, id=session_id, owner=user)
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
    ext_token = request.headers.get('X-Ext-Token', '').strip()
    profile = _profile_for_token(ext_token) if ext_token else None
    user = profile.user if profile else request.user
    session = get_object_or_404(InterviewSession, id=session_id, owner=user)
    session.delete()
    return JsonResponse({"ok": True})


@csrf_exempt
@require_POST
def api_edit_session(request, session_id):
    if (r := _auth_required(request)): return r
    ext_token = request.headers.get('X-Ext-Token', '').strip()
    profile = _profile_for_token(ext_token) if ext_token else None
    user = profile.user if profile else request.user
    session = get_object_or_404(InterviewSession, id=session_id, owner=user)
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
    ext_token = request.headers.get('X-Ext-Token', '').strip()
    profile = _profile_for_token(ext_token) if ext_token else None
    user = profile.user if profile else request.user
    session = get_object_or_404(InterviewSession, id=session_id, owner=user)
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
    ext_token = request.headers.get('X-Ext-Token', '').strip()
    profile = _profile_for_token(ext_token) if ext_token else None
    user = profile.user if profile else request.user
    session = get_object_or_404(InterviewSession, id=session_id, owner=user)
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
        speaker_type=TranscriptEntry.TYPE_NOTE,
    )
    return JsonResponse({"ok": True, "id": str(entry.id), "content": entry.content})


# ── TEAMS RECORDER ────────────────────────────────────────────────────────────

@csrf_exempt
def api_meeting_participants(request, session_id):
    """GET list of participants / POST to add one."""
    if (r := _auth_required(request)): return r
    ext_token = request.headers.get('X-Ext-Token', '').strip()
    profile = _profile_for_token(ext_token) if ext_token else None
    user = profile.user if profile else request.user
    session = get_object_or_404(InterviewSession, id=session_id, owner=user)

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
    ext_token = request.headers.get('X-Ext-Token', '').strip()
    profile = _profile_for_token(ext_token) if ext_token else None
    user = profile.user if profile else request.user
    p = get_object_or_404(MeetingParticipant, id=participant_id, session__id=session_id, session__owner=user)
    p.delete()
    return JsonResponse({"ok": True})


@csrf_exempt
@require_POST
def api_scan_participants(request, session_id):
    """Receive a screenshot, call Groq vision to extract participant names."""
    import base64, re
    if (r := _auth_required(request)): return r
    ext_token = request.headers.get('X-Ext-Token', '').strip()
    profile = _profile_for_token(ext_token) if ext_token else None
    user = profile.user if profile else request.user
    get_object_or_404(InterviewSession, id=session_id, owner=user)

    screenshot = request.FILES.get("screenshot")
    if not screenshot:
        return JsonResponse({"error": "No screenshot provided"}, status=400)

    api_key = getattr(settings, "GROQ_API_KEY", None)
    if not api_key:
        return JsonResponse({"error": "GROQ_API_KEY not configured"}, status=500)

    mime = screenshot.content_type or "image/png"
    b64 = base64.b64encode(screenshot.read()).decode("utf-8")

    try:
        client = openai_lib.OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
        resp = client.chat.completions.create(
            model="llama-3.2-11b-vision-preview",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    {"type": "text", "text": (
                        "This is a screenshot of a Teams, Zoom, or Google Meet meeting. "
                        "Extract the following and return ONLY a JSON object (no markdown, no explanation):\n"
                        "1. \"names\": array of all participant/attendee names visible in the participants panel, video tiles, or attendee list\n"
                        "2. \"speakers\": array of names of people currently speaking or who have a speaking indicator\n"
                        "3. \"title\": the meeting title/subject shown at the top of the screen, or empty string if not visible\n"
                        "Example: {\"names\": [\"Alice\", \"Bob\"], \"speakers\": [\"Alice\"], \"title\": \"Sprint Planning\"}\n"
                        "If no data is visible for a field, use an empty array or empty string."
                    )},
                ],
            }],
            max_tokens=600,
        )
        content = resp.choices[0].message.content.strip()
        match = re.search(r"\{.*\}", content, re.DOTALL)
        parsed = json.loads(match.group()) if match else {}
        names = [n for n in (parsed.get("names") or []) if isinstance(n, str) and n.strip()]
        speakers = [n for n in (parsed.get("speakers") or []) if isinstance(n, str) and n.strip()]
        title = str(parsed.get("title") or "").strip()
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"names": names, "speakers": speakers, "title": title})


@csrf_exempt
@require_POST
def api_update_entry_speaker(request, session_id, entry_id):
    """Assign a speaker_name to a transcript entry."""
    if (r := _auth_required(request)): return r
    ext_token = request.headers.get('X-Ext-Token', '').strip()
    profile = _profile_for_token(ext_token) if ext_token else None
    user = profile.user if profile else request.user
    entry = get_object_or_404(TranscriptEntry, id=entry_id, session__id=session_id, session__owner=user)
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
    ext_token = request.headers.get('X-Ext-Token', '').strip()
    profile = _profile_for_token(ext_token) if ext_token else None
    user = profile.user if profile else request.user
    session = get_object_or_404(InterviewSession, id=session_id, owner=user)
    client, model, provider = _get_chat_client()
    if not client:
        return JsonResponse({"error": "No AI key set. Add OPENROUTER_API_KEY or GROQ_API_KEY."}, status=500)

    transcripts = session.transcripts.order_by("created_at")
    if not transcripts.exists():
        return JsonResponse({"error": "No transcript to summarize"}, status=400)

    def _fmt(e):
        _type_label = {'microphone': 'You', 'system': 'Interviewer', 'note': 'Note'}.get(e.speaker_type, e.speaker_type)
        label = e.speaker_name if e.speaker_name else _type_label
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
    session_count = InterviewSession.objects.filter(owner=request.user).count()
    transcript_count = TE.objects.filter(session__owner=request.user).count()
    ai_count = AI.objects.filter(session__owner=request.user).count()

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
        if session.prep_notes:
            parts.append(f"\nInterview preparation notes:\n{session.prep_notes[:1500]}")
    return "\n".join(parts)


# ── STRIPE BILLING ─────────────────────────────────────────────────────────────

@login_required
def billing_checkout(request, plan):
    """Create a Stripe Checkout session and redirect to it."""
    if plan not in ("pro", "team"):
        return redirect("pricing")
    if not settings.STRIPE_SECRET_KEY:
        return render(request, "interview/billing_unavailable.html")

    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY

    price_id = settings.STRIPE_PRICE_PRO if plan == "pro" else settings.STRIPE_PRICE_TEAM
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    customer_id = profile.stripe_customer_id or None
    if not customer_id:
        customer = stripe.Customer.create(
            email=request.user.email,
            metadata={"user_id": request.user.id},
        )
        profile.stripe_customer_id = customer.id
        profile.save(update_fields=["stripe_customer_id"])
        customer_id = customer.id

    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=request.build_absolute_uri("/billing/success/"),
        cancel_url=request.build_absolute_uri("/pricing/"),
    )
    return redirect(session.url, permanent=False)


@login_required
def billing_success(request):
    return render(request, "interview/billing_success.html")


@login_required
def billing_portal(request):
    """Redirect to Stripe customer portal to manage subscription."""
    if not settings.STRIPE_SECRET_KEY:
        return render(request, "interview/billing_unavailable.html")
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.stripe_customer_id:
        return redirect("pricing")
    portal = stripe.billing_portal.Session.create(
        customer=profile.stripe_customer_id,
        return_url=request.build_absolute_uri("/"),
    )
    return redirect(portal.url, permanent=False)


@csrf_exempt
def stripe_webhook(request):
    """Handle Stripe webhook events — checkout.session.completed and subscription.deleted."""
    if not settings.STRIPE_WEBHOOK_SECRET:
        return HttpResponse(status=400)

    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY

    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        return HttpResponse(status=400)

    if event["type"] == "checkout.session.completed":
        session_obj = event["data"]["object"]
        customer_id = session_obj.get("customer")
        sub_id = session_obj.get("subscription", "")
        plan = "pro"
        # Determine plan from price (look up subscription line items)
        try:
            sub = stripe.Subscription.retrieve(sub_id)
            price_id = sub["items"]["data"][0]["price"]["id"]
            if price_id == settings.STRIPE_PRICE_TEAM:
                plan = "team"
        except Exception:
            pass
        try:
            profile = UserProfile.objects.get(stripe_customer_id=customer_id)
            profile.plan = plan
            profile.stripe_subscription_id = sub_id
            profile.save(update_fields=["plan", "stripe_subscription_id"])
        except UserProfile.DoesNotExist:
            pass

    elif event["type"] in ("customer.subscription.deleted", "customer.subscription.updated"):
        sub = event["data"]["object"]
        customer_id = sub.get("customer")
        status = sub.get("status", "")
        try:
            profile = UserProfile.objects.get(stripe_customer_id=customer_id)
            if status in ("canceled", "unpaid", "incomplete_expired"):
                profile.plan = UserProfile.PLAN_FREE
                profile.stripe_subscription_id = ""
                profile.save(update_fields=["plan", "stripe_subscription_id"])
        except UserProfile.DoesNotExist:
            pass

    return HttpResponse(status=200)


# ── PER-USER ANALYTICS ─────────────────────────────────────────────────────────

@csrf_exempt
def api_stats(request):
    """Return per-user session and activity stats. Supports X-Ext-Token (overlay) and session auth."""
    ext_token = request.headers.get('X-Ext-Token', '').strip()
    profile = _profile_for_token(ext_token) if ext_token else None
    if profile:
        user = profile.user
    elif request.user.is_authenticated:
        user = request.user
    else:
        return JsonResponse({"error": "authentication required"}, status=401)
    sessions = InterviewSession.objects.filter(owner=user)
    total = sessions.count()
    active = sessions.filter(status=InterviewSession.STATUS_ACTIVE).count()
    ended = sessions.filter(status=InterviewSession.STATUS_ENDED).count()
    transcript_count = TranscriptEntry.objects.filter(session__owner=user).count()
    ai_count = AIMessage.objects.filter(session__owner=user).count()

    try:
        profile = user.profile
        plan = profile.plan
        limit = profile.session_limit
    except UserProfile.DoesNotExist:
        plan = "free"
        limit = UserProfile.FREE_SESSION_LIMIT

    recent = sessions.order_by("-created_at")[:5]

    return JsonResponse({
        "plan": plan,
        "session_limit": limit,
        "sessions_total": total,
        "sessions_active": active,
        "sessions_ended": ended,
        "transcripts_total": transcript_count,
        "ai_responses_total": ai_count,
        "recent_sessions": [
            {"id": str(s.id), "title": s.title, "status": s.status,
             "created_at": s.created_at.isoformat() if s.created_at else None}
            for s in recent
        ],
    })


# ── POST-SESSION SCORING ───────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def api_session_score(request, session_id):
    """Generate AI-powered performance score and feedback for a completed session."""
    if (r := _auth_required(request)): return r
    ext_token = request.headers.get('X-Ext-Token', '').strip()
    profile = _profile_for_token(ext_token) if ext_token else None
    user = profile.user if profile else request.user
    session = get_object_or_404(InterviewSession, id=session_id, owner=user)

    client, model, provider = _get_chat_client()
    if not client:
        return JsonResponse({"error": "No AI key set."}, status=500)

    transcripts = session.transcripts.order_by("created_at")
    ai_messages = session.ai_messages.order_by("created_at")

    if not transcripts.exists():
        return JsonResponse({"error": "No transcript to score"}, status=400)

    def _fmt(e):
        _type_label = {'microphone': 'You', 'system': 'Interviewer', 'note': 'Note'}.get(e.speaker_type, e.speaker_type)
        label = e.speaker_name if e.speaker_name else _type_label
        return f"[{label}]: {e.content}"

    transcript_text = "\n".join(_fmt(e) for e in transcripts)
    ai_text = "\n".join(f"Q: {m.trigger_text}\nA: {m.content}" for m in ai_messages)

    system_msg = (
        "You are an expert interview/meeting performance coach. "
        "Score the session and give actionable feedback. "
        "Return ONLY valid JSON in this exact format:\n"
        '{"overall_score": <1-10>, '
        '"communication_score": <1-10>, '
        '"clarity_score": <1-10>, '
        '"engagement_score": <1-10>, '
        '"summary": "2-3 sentence performance summary", '
        '"strengths": ["strength 1", "strength 2"], '
        '"improvements": ["improvement 1", "improvement 2"], '
        '"next_steps": ["actionable step 1", "actionable step 2"]}'
    )

    session_type = "interview" if session.session_type == InterviewSession.SESSION_TYPE_INTERVIEW else "meeting"
    user_msg = (
        f"Session type: {session_type}\n"
        f"Role/Title: {session.title}\n"
        f"Company: {session.company or 'N/A'}\n\n"
        f"Transcript:\n{transcript_text[:3000]}\n\n"
        f"AI responses used:\n{ai_text[:1000]}"
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}],
            max_tokens=800,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
            if raw.endswith("```"):
                raw = raw[:-3]
        result = json.loads(raw)
        AIMessage.objects.create(
            session=session,
            trigger_text="[Session Score]",
            content=json.dumps(result),
        )
        return JsonResponse(result)
    except json.JSONDecodeError:
        return JsonResponse({"error": "AI returned invalid JSON"}, status=500)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=500)


@login_required
def onboarding_view(request):
    return render(request, "interview/onboarding.html")


@csrf_exempt
@require_POST
def api_login(request):
    """Desktop overlay login: POST {username, password} → {token, plan, session_limit, sessions_used}."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return JsonResponse({"error": "username and password required"}, status=400)

    user = authenticate(request, username=username, password=password)
    if user is None:
        return JsonResponse({"error": "Invalid credentials"}, status=401)

    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        profile, _ = UserProfile.objects.get_or_create(user=user)

    used = InterviewSession.objects.filter(owner=user).count()
    return JsonResponse({
        "token": profile.ext_token,
        "plan": profile.plan,
        "session_limit": profile.session_limit,
        "sessions_used": used,
        "username": user.username,
    })


@csrf_exempt
@require_POST
def api_new_session(request):
    """Desktop overlay: create a new session. POST {title?, company?, role?} → {session_id}."""
    ext_token = request.headers.get('X-Ext-Token', '').strip()
    profile = _profile_for_token(ext_token) if ext_token else None
    if not profile:
        return JsonResponse({"error": "invalid token"}, status=401)

    ok, sessions_used, limit = _check_session_limit(profile.user)
    if not ok:
        return JsonResponse({
            "error": "session_limit_reached",
            "sessions_used": sessions_used,
            "session_limit": limit,
        }, status=403)

    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}

    title = (data.get("title") or "").strip() or f"Session {sessions_used + 1}"
    company = (data.get("company") or profile.company or "").strip()
    session_type = data.get("session_type", InterviewSession.SESSION_TYPE_INTERVIEW)

    extra_context = (data.get("extra_context") or profile.background or "").strip()
    session = InterviewSession.objects.create(
        owner=profile.user,
        title=title,
        company=company,
        session_type=session_type,
        status=InterviewSession.STATUS_ACTIVE,
        extra_context=extra_context,
        prep_notes=_DEFAULT_PREP_NOTES,
    )
    return JsonResponse({
        "session_id": str(session.id),
        "title": session.title,
        "sessions_used": sessions_used + 1,
    })


@csrf_exempt
def api_session_context(request, session_id):
    """GET or PUT the editable context fields for a session (extra_context + prep_notes)."""
    ext_token = request.headers.get('X-Ext-Token', '').strip()
    profile = _profile_for_token(ext_token) if ext_token else None
    if not profile and not request.user.is_authenticated:
        return JsonResponse({"error": "unauthorized"}, status=401)

    user = profile.user if profile else request.user
    session = get_object_or_404(InterviewSession, id=session_id, owner=user)

    if request.method == "GET":
        return JsonResponse({
            "session_id": str(session.id),
            "title": session.title,
            "company": session.company,
            "extra_context": session.extra_context,
            "prep_notes": session.prep_notes,
            "job_description": session.job_description,
        })

    if request.method == "PUT":
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "invalid JSON"}, status=400)

        fields = {}
        if "extra_context" in data:
            fields["extra_context"] = data["extra_context"].strip()
        if "prep_notes" in data:
            fields["prep_notes"] = data["prep_notes"].strip()
        if "job_description" in data:
            fields["job_description"] = data["job_description"].strip()
        if fields:
            InterviewSession.objects.filter(id=session_id).update(**fields)
        return JsonResponse({"ok": True})

    return JsonResponse({"error": "GET or PUT required"}, status=405)


# ── Admin: DB Sync Portal ──────────────────────────────────────────────────────

@login_required
def admin_db_sync(request):
    if not request.user.is_staff:
        return HttpResponseForbidden("Staff only")
    from .models import DbSyncLog
    logs = DbSyncLog.objects.all()[:50]
    mysql_enabled = getattr(settings, "MYSQL_BACKUP_ENABLED", False)
    return render(request, "interview/admin_db_sync.html", {
        "logs": logs,
        "mysql_enabled": mysql_enabled,
    })


@login_required
@require_POST
def admin_db_sync_action(request):
    if not request.user.is_staff:
        return HttpResponseForbidden("Staff only")
    if not getattr(settings, "MYSQL_BACKUP_ENABLED", False):
        messages.error(request, "MySQL backup is not configured (MYSQL_HOST env var missing).")
        return redirect("admin_db_sync")
    action = request.POST.get("action")
    if action == "backup":
        from .db_sync import backup_to_mysql
        count, err = backup_to_mysql(triggered_by="admin_manual")
        if err:
            messages.error(request, f"Backup failed: {err}")
        else:
            messages.success(request, f"Backup complete: {count} records → MySQL")
    elif action == "restore":
        from .db_sync import restore_from_mysql
        count, err = restore_from_mysql(triggered_by="admin_manual")
        if err:
            messages.error(request, f"Restore failed: {err}")
        else:
            messages.success(request, f"Restore complete: {count} records ← MySQL")
    else:
        messages.error(request, "Unknown action")
    return redirect("admin_db_sync")


# ── Templates ─────────────────────────────────────────────────────────────────

@login_required
def templates_page(request):
    from .management.commands.seed_templates import AI_HELP_DEFAULTS, MEETING_AI_DEFAULTS
    user = request.user
    if not PromptTemplate.objects.filter(owner=user).exists():
        for tpl in AI_HELP_DEFAULTS:
            PromptTemplate.objects.create(owner=user, template_type="ai_help", **tpl)
        for tpl in MEETING_AI_DEFAULTS:
            PromptTemplate.objects.create(owner=user, template_type="meeting_ai", **tpl)
    templates = PromptTemplate.objects.filter(owner=user)
    return render(request, "interview/templates_page.html", {"templates": templates})


@login_required
def api_templates_list(request):
    tpl_type = request.GET.get("type")
    # Return the user's own templates plus superuser-owned shared templates
    admin_ids = list(User.objects.filter(is_superuser=True).values_list("id", flat=True))
    owner_ids = list({request.user.id} | set(admin_ids))
    qs = PromptTemplate.objects.filter(owner_id__in=owner_ids, is_active=True)
    if tpl_type:
        qs = qs.filter(template_type=tpl_type)
    data = [
        {
            "id": t.pk,
            "pk": t.pk,
            "name": t.name,
            "description": t.description,
            "prompt": t.prompt,
            "icon": t.icon,
            "template_type": t.template_type,
            "order": t.order,
        }
        for t in qs
    ]
    return JsonResponse(data, safe=False)


@login_required
@require_POST
def api_template_create(request):
    try:
        body = json.loads(request.body)
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    t = PromptTemplate.objects.create(
        owner=request.user,
        name=body.get("name", "Untitled"),
        description=body.get("description", ""),
        prompt=body.get("prompt", ""),
        icon=body.get("icon", "✨"),
        template_type=body.get("template_type", "ai_help"),
        order=body.get("order", 0),
        is_active=body.get("is_active", True),
    )
    return JsonResponse({"id": t.pk, "status": "created"})


@login_required
@require_POST
def api_template_update(request, template_id):
    t = get_object_or_404(PromptTemplate, pk=template_id, owner=request.user)
    try:
        body = json.loads(request.body)
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    for field in ("name", "description", "prompt", "icon", "template_type", "order", "is_active"):
        if field in body:
            setattr(t, field, body[field])
    t.save()
    return JsonResponse({"id": t.pk, "status": "updated"})


@login_required
@require_POST
def api_template_delete(request, template_id):
    t = get_object_or_404(PromptTemplate, pk=template_id, owner=request.user)
    t.delete()
    return JsonResponse({"status": "deleted"})
