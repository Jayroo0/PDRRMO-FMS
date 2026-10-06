(function () {
    let printValues = [];
    let hiddenColumns = [];
    let originalViews = [];
    let isPrepared = false;

    function addPrintHeader() {
        if (document.querySelector(".dashboard-print-header")) {
            return;
        }

        const header = document.createElement("header");
        const title = document.createElement("h1");
        const subtitle = document.createElement("p");
        const timestamp = document.createElement("time");

        header.className = "dashboard-print-header";
        title.textContent = document.title.replace(/^\s*PDRRMO\s*[|:-]\s*/i, "").trim();
        subtitle.textContent = "PDRRMO Fleet Management Report";
        timestamp.className = "dashboard-print-timestamp";
        header.append(title, subtitle, timestamp);
        document.body.insertBefore(header, document.body.firstChild);
    }

    function readableControlValues(form) {
        const values = [];
        form.querySelectorAll("select").forEach((select) => {
            const selectedOption = select.options[select.selectedIndex];
            if (selectedOption && selectedOption.textContent.trim()) {
                values.push(selectedOption.textContent.trim());
            }
        });

        form.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"])').forEach((input) => {
            if (input.type === "checkbox" || input.type === "radio") {
                const label = input.closest("label") || form.querySelector(`label[for="${input.id}"]`);
                const value = label ? label.textContent.trim() : "";
                if (value) {
                    values.push(value);
                } else {
                    const status = form.querySelector("span");
                    if (status && status.textContent.trim()) {
                        values.push(status.textContent.trim());
                    }
                }
            } else if (input.value.trim()) {
                values.push(input.value.trim());
            }
        });

        return [...new Set(values)];
    }

    function preparePrint() {
        if (isPrepared) {
            return;
        }
        isPrepared = true;
        addPrintHeader();

        originalViews = [];
        document.querySelectorAll("[data-view-list]").forEach((list) => {
            const controls = list.previousElementSibling?.classList.contains("dashboard-view-controls")
                ? list.previousElementSibling
                : null;
            originalViews.push({
                list,
                mode: list.dataset.viewMode
            });
            list.dataset.viewMode = "list";
            controls?.querySelectorAll("button").forEach((button) => {
                button.setAttribute("aria-pressed", String(button.dataset.viewOption === "list"));
            });
        });

        const timestamp = document.querySelector(".dashboard-print-timestamp, #print-date-stamp");
        if (timestamp) {
            timestamp.textContent = new Intl.DateTimeFormat(undefined, {
                dateStyle: "medium",
                timeStyle: "short"
            }).format(new Date());
        }

        printValues = [];
        document.querySelectorAll("form").forEach((form) => {
            const values = readableControlValues(form);
            if (values.length === 0 || !form.parentElement) {
                return;
            }

            const value = document.createElement("span");
            value.className = "dashboard-print-value";
            value.textContent = values.join(" · ");
            form.parentElement.insertBefore(value, form);
            printValues.push(value);
        });

        hiddenColumns = [];
        document.querySelectorAll('[data-view-type="table"] table').forEach((table) => {
            const headerCells = table.querySelectorAll("thead tr:first-child th");
            headerCells.forEach((header, index) => {
                if (!/\b(action|controls?|override)\b/i.test(header.textContent)) {
                    return;
                }

                const columnIndex = header.cellIndex;
                [header, ...table.querySelectorAll(`tbody tr td:nth-child(${columnIndex + 1})`)].forEach((cell) => {
                    cell.classList.add("print-hidden-column");
                    hiddenColumns.push(cell);
                });
            });
        });
    }

    function cleanupPrint() {
        printValues.forEach((value) => value.remove());
        hiddenColumns.forEach((cell) => cell.classList.remove("print-hidden-column"));
        originalViews.forEach(({ list, mode }) => {
            const controls = list.previousElementSibling?.classList.contains("dashboard-view-controls")
                ? list.previousElementSibling
                : null;
            if (mode) {
                list.dataset.viewMode = mode;
            } else {
                delete list.dataset.viewMode;
            }
            controls?.querySelectorAll("button").forEach((button) => {
                button.setAttribute("aria-pressed", String(button.dataset.viewOption === mode));
            });
        });
        printValues = [];
        hiddenColumns = [];
        originalViews = [];
        isPrepared = false;
    }

    document.addEventListener("DOMContentLoaded", () => {
        addPrintHeader();
        document.querySelectorAll(".dashboard-print-trigger").forEach((button) => {
            button.addEventListener("click", () => window.print());
        });
    });

    window.addEventListener("beforeprint", preparePrint);
    window.addEventListener("afterprint", cleanupPrint);
})();
