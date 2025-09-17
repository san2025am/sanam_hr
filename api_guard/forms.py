# في ملف api_guard/forms.py

from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import User

class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        # الطريقة الصحيحة لإضافة حقل جديد
        fields = UserCreationForm.Meta.fields + ('role',)

class CustomUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        # هنا نحدد الحقول بشكل صريح لتجنب المشكلة
        fields = ('username', 'email', 'first_name', 'last_name', 'role', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')

