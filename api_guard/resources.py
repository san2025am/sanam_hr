from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget

from .models import Employee, Location, Report, Request


class EmployeeResource(resources.ModelResource):
    supervisor = fields.Field(
        attribute='supervisor',
        column_name='supervisor',
        widget=ForeignKeyWidget(Employee, 'full_name')
    )

    class Meta:
        model = Employee
        import_id_fields = ('id',)
        fields = (
            'id', 'full_name', 'national_id', 'phone_number',
            'bank_name', 'bank_account', 'hire_date', 'monthly_leave_quota_hours', 'supervisor',
        )


class LocationResource(resources.ModelResource):
    class Meta:
        model = Location
        import_id_fields = ('id',)
        fields = (
            'id', 'name', 'client_name', 'gps_coordinates', 'gps_radius', 'use_polygon', 'instructions',
        )


class ReportResource(resources.ModelResource):
    employee = fields.Field(
        attribute='employee', column_name='employee', widget=ForeignKeyWidget(Employee, 'full_name')
    )
    location = fields.Field(
        attribute='location', column_name='location', widget=ForeignKeyWidget(Location, 'name')
    )

    class Meta:
        model = Report
        import_id_fields = ('id',)
        fields = (
            'id', 'employee', 'location', 'report_type', 'status', 'description', 'created_at',
        )
        export_order = fields


class RequestResource(resources.ModelResource):
    employee = fields.Field(
        attribute='employee', column_name='employee', widget=ForeignKeyWidget(Employee, 'full_name')
    )
    approver = fields.Field(
        attribute='approver', column_name='approver', widget=ForeignKeyWidget(Employee, 'full_name')
    )

    class Meta:
        model = Request
        import_id_fields = ('id',)
        fields = (
            'id', 'employee', 'request_type', 'status', 'approver', 'description', 'created_at',
            'leave_start', 'leave_end', 'leave_hours',
        )
        export_order = fields

