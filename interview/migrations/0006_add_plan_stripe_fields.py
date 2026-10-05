from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("interview", "0005_add_owner_to_session"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="plan",
            field=models.CharField(
                choices=[("free", "Free"), ("pro", "Pro"), ("team", "Team")],
                default="free",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="stripe_customer_id",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="stripe_subscription_id",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
