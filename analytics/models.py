from django.db import models

# Create your models here.
class UsageMetric(models.Model):
    student = models.ForeignKey("students.Student", on_delete=models.CASCADE)
    recorded_at = models.DateTimeField(auto_now_add=True)
    api_calls = models.IntegerField(default=0)
    daily_active_users = models.IntegerField(default=0)
    feature_slug = models.CharField(max_length=100)

    class Meta:
        indexes = [
            models.Index(fields=["student", "recorded_at"]),
        ]
        ordering = ["-recorded_at"]