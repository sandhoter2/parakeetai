from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("interview", "0002_userprofile"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="ext_token",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Static token used by the Electron overlay to authenticate API calls.",
                max_length=64,
                unique=True,
            ),
            preserve_default=False,
        ),
    ]
