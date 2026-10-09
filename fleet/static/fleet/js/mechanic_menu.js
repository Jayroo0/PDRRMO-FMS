document.addEventListener('DOMContentLoaded', function () {
    const menuDrawer = document.getElementById('mechanicMenuDrawer');
    if (!menuDrawer) {
        return;
    }

    menuDrawer.querySelectorAll('[data-menu-action]').forEach(button => {
        button.addEventListener('click', function () {
            menuDrawer.dataset.pendingAction = this.dataset.menuAction;
            bootstrap.Offcanvas.getOrCreateInstance(menuDrawer).hide();
        });
    });

    menuDrawer.addEventListener('hidden.bs.offcanvas', function () {
        const action = menuDrawer.dataset.pendingAction;
        delete menuDrawer.dataset.pendingAction;

        if (action === 'print') {
            window.print();
        } else if (action === 'generate-report') {
            const reportModal = document.getElementById('generateReportModal');
            bootstrap.Modal.getOrCreateInstance(reportModal).show();
        }
    });
});
