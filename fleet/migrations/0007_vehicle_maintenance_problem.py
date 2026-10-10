from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fleet', '0006_vehicle_deployment_purpose'),
    ]

    operations = [
        migrations.AddField(
            model_name='vehicle',
            name='maintenance_problem',
            field=models.CharField(blank=True, max_length=1000),
        ),
    ]
