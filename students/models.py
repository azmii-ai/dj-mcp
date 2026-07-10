from django.db import models

# Create your models here.


class Student(models.Model):
    name = models.CharField(max_length=100)
    tenant_id = models.IntegerField(db_index=True)
    age = models.IntegerField()
    email = models.EmailField()
    enrollment_date = models.DateField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)
    plan = models.CharField(max_length=50, default="free")
    mrr = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    health_score = models.IntegerField(default=100)
    is_active = models.BooleanField(default=True)
    last_active_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("tenant_id", "email")

    def __str__(self):
        return self.name


class StudentNote(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="notes")
    tenant_id = models.IntegerField(db_index=True)
    content = models.TextField()
    note_type = models.CharField(
        max_length=50,
        choices=[
            ("observation", "Observation"),
            ("action_taken", "Action Taken"),
            ("risk_flag", "Risk Flag"),
            ("opportunity", "Opportunity"),
            ("general", "General"),
        ],
        default="general",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by_agent = models.BooleanField(default=False)

    def __str__(self):
        return f"Note for {self.student.name} - {self.note_type}"
