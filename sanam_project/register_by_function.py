from django.apps import apps

def safe_register(site, dotted_labels):
    for label in dotted_labels:
        try:
            app_label, model_name = label.split(".")
            Model = apps.get_model(app_label, model_name)
            site.register(Model)
        except Exception:
            pass
