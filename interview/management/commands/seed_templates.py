from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from interview.models import PromptTemplate

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


class Command(BaseCommand):
    help = "Seed default AI Help and Meeting AI templates for all users (skips users who already have templates)"

    def add_arguments(self, parser):
        parser.add_argument("--user", type=str, help="Username to seed (default: all users)")
        parser.add_argument("--overwrite", action="store_true", help="Overwrite existing templates")

    def handle(self, *args, **options):
        username = options.get("user")
        overwrite = options.get("overwrite", False)

        if username:
            users = User.objects.filter(username=username)
        else:
            users = User.objects.all()

        for user in users:
            existing = PromptTemplate.objects.filter(owner=user).count()
            if existing > 0 and not overwrite:
                self.stdout.write(f"  Skipping {user.username} — already has {existing} templates")
                continue

            if overwrite:
                PromptTemplate.objects.filter(owner=user).delete()

            created = 0
            for tpl in AI_HELP_DEFAULTS:
                PromptTemplate.objects.create(owner=user, template_type="ai_help", **tpl)
                created += 1
            for tpl in MEETING_AI_DEFAULTS:
                PromptTemplate.objects.create(owner=user, template_type="meeting_ai", **tpl)
                created += 1

            self.stdout.write(self.style.SUCCESS(f"  Seeded {created} templates for {user.username}"))
