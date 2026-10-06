(function () {
    const viewOptions = ["tile", "grid", "list"];
    const viewLabels = {
        tile: "Tile",
        grid: "Grid",
        list: "List"
    };

    function getSavedView(key) {
        try {
            const savedView = window.localStorage.getItem(key);
            return viewOptions.includes(savedView) ? savedView : null;
        } catch (error) {
            console.warn("Dashboard view preference could not be read.", error);
            return null;
        }
    }

    function saveView(key, view) {
        try {
            window.localStorage.setItem(key, view);
        } catch (error) {
            console.warn("Dashboard view preference could not be saved.", error);
        }
    }

    function addCellLabels(list) {
        const table = list.querySelector("table");
        if (!table) {
            return;
        }

        const labels = Array.from(table.querySelectorAll("thead th"), (header) =>
            header.textContent.trim().replace(/\s+/g, " ")
        );

        table.querySelectorAll("tbody tr").forEach((row) => {
            Array.from(row.cells).forEach((cell, index) => {
                cell.dataset.viewLabel = cell.colSpan > 1 ? "" : labels[index] || "";
            });
        });
    }

    function initializeList(list) {
        const key = `dashboard-view:${list.dataset.viewList}`;
        const defaultView = viewOptions.includes(list.dataset.viewDefault)
            ? list.dataset.viewDefault
            : "list";
        const selectedView = getSavedView(key) || defaultView;
        const controls = document.createElement("div");
        controls.className = "dashboard-view-controls";
        controls.setAttribute("role", "group");
        controls.setAttribute("aria-label", "Choose data view");

        list.dataset.viewMode = selectedView;

        if (list.dataset.viewType === "table") {
            addCellLabels(list);
        }

        viewOptions.forEach((view) => {
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = viewLabels[view];
            button.dataset.viewOption = view;
            button.setAttribute("aria-pressed", String(view === selectedView));
            button.addEventListener("click", () => {
                list.dataset.viewMode = view;
                controls.querySelectorAll("button").forEach((option) => {
                    option.setAttribute("aria-pressed", String(option === button));
                });
                saveView(key, view);
            });
            controls.appendChild(button);
        });

        list.parentElement.insertBefore(controls, list);
    }

    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("[data-view-list]").forEach(initializeList);
    });
})();
