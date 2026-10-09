document.addEventListener('DOMContentLoaded', function () {
    const reportKind = document.getElementById('report-kind');
    const maintenanceCategoryField = document.getElementById('maintenance-category-field');
    if (reportKind && maintenanceCategoryField) {
        const updateMaintenanceCategory = () => {
            maintenanceCategoryField.classList.toggle('d-none', reportKind.value !== 'maintenance');
        };
        reportKind.addEventListener('change', updateMaintenanceCategory);
        updateMaintenanceCategory();
    }

    const reportPeriod = document.getElementById('report-period');
    if (!reportPeriod) {
        return;
    }

    const updateReportDateFields = () => {
        document.querySelectorAll('.report-date-field').forEach(field => {
            const active = field.dataset.period === reportPeriod.value;
            field.classList.toggle('d-none', !active);
            field.querySelectorAll('input').forEach(input => {
                input.disabled = !active;
                input.required = active;
            });
        });
    };

    reportPeriod.addEventListener('change', updateReportDateFields);
    updateReportDateFields();
});
