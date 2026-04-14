(function () {
    "use strict";

    var THEME_KEY = "gr-theme";

    function getCsrfToken() {
        var input = document.querySelector("[name=csrfmiddlewaretoken]");
        if (input && input.value) {
            return input.value;
        }

        var cookie = document.cookie.match(/csrftoken=([^;]+)/);
        return cookie ? cookie[1] : "";
    }

    function setTheme(theme) {
        document.documentElement.setAttribute("data-theme", theme);
        try {
            localStorage.setItem(THEME_KEY, theme);
        } catch (error) {
            console.warn("Nao foi possivel persistir tema.", error);
        }

        var icon = document.querySelector("[data-theme-toggle] i");
        if (icon) {
            icon.className = theme === "dark" ? "bi bi-brightness-high" : "bi bi-moon-stars";
        }
    }

    function initTheme() {
        var initialTheme = "light";
        try {
            initialTheme = localStorage.getItem(THEME_KEY) || initialTheme;
        } catch (error) {
            initialTheme = "light";
        }

        if (!localStorage.getItem(THEME_KEY) && window.matchMedia("(prefers-color-scheme: dark)").matches) {
            initialTheme = "dark";
        }

        setTheme(initialTheme);

        var toggle = document.querySelector("[data-theme-toggle]");
        if (toggle) {
            toggle.addEventListener("click", function () {
                var currentTheme = document.documentElement.getAttribute("data-theme") || "light";
                setTheme(currentTheme === "dark" ? "light" : "dark");
            });
        }
    }

    function markActiveSidebarLink() {
        var currentPath = window.location.pathname.replace(/\/$/, "");
        var links = document.querySelectorAll(".sidebar nav a[href]");

        links.forEach(function (link) {
            var href = link.getAttribute("href");
            if (!href || href === "#" || href.indexOf("javascript:") === 0) {
                return;
            }

            var linkPath = href.replace(/\/$/, "");
            if (linkPath === currentPath) {
                link.classList.add("active");
                var submenu = link.closest(".submenu");
                if (submenu) {
                    var parentLi = submenu.closest("li.has-submenu");
                    if (parentLi) {
                        parentLi.classList.add("open");
                    }
                }
            }
        });
    }

    function toggleSubmenu(element) {
        var parentLi = element.parentElement;
        var wasOpen = parentLi.classList.contains("open");

        document.querySelectorAll(".sidebar nav li.has-submenu").forEach(function (item) {
            item.classList.remove("open");
        });

        if (!wasOpen) {
            parentLi.classList.add("open");
        }
    }

    window.toggleSubmenu = toggleSubmenu;

    function initSubmenuToggles() {
        document.querySelectorAll(".js-submenu-toggle").forEach(function (toggle) {
            toggle.addEventListener("click", function (event) {
                event.preventDefault();
                toggleSubmenu(this);
            });
        });
    }

    function initNotificationDropdown() {
        var notificationIcon = document.querySelector(".notification-icon");
        var notificationDropdown = document.querySelector("#notificationDropdown");

        if (!notificationIcon || !notificationDropdown) {
            return;
        }

        notificationIcon.addEventListener("click", function (event) {
            event.preventDefault();
            notificationDropdown.style.display = notificationDropdown.style.display === "block" ? "none" : "block";
        });

        document.addEventListener("click", function (event) {
            if (!notificationIcon.contains(event.target) && !notificationDropdown.contains(event.target)) {
                notificationDropdown.style.display = "none";
            }
        });
    }

    function initDeleteButtons() {
        document.querySelectorAll(".btn-delete[data-id], .btn-delete[data-delete-url]").forEach(function (button) {
            button.addEventListener("click", function (event) {
                event.preventDefault();
                var id = button.getAttribute("data-id");
                var explicitDeleteUrl = button.getAttribute("data-delete-url");

                if (!window.confirm("Tem certeza que deseja excluir este item?")) {
                    return;
                }

                var candidateUrls = [];
                if (explicitDeleteUrl) {
                    candidateUrls.push(explicitDeleteUrl);
                }

                if (id) {
                    var currentUrl = window.location.pathname.replace(/\/$/, "");
                    candidateUrls.push(currentUrl + "/" + id + "/delete/");
                    candidateUrls.push(currentUrl + "/" + id + "/deletar/");
                }

                candidateUrls = candidateUrls.filter(function (url, index, arr) {
                    return !!url && arr.indexOf(url) === index;
                });

                if (!candidateUrls.length) {
                    window.alert("URL de exclusão não encontrada");
                    return;
                }

                var methods = ["DELETE", "POST"];

                function parseResponse(response) {
                    var contentType = response.headers.get("content-type") || "";
                    if (contentType.indexOf("application/json") !== -1) {
                        return response.json();
                    }
                    if (response.redirected) {
                        return Promise.resolve({ status: "success", redirect: response.url });
                    }
                    return Promise.resolve({ status: response.ok ? "success" : "error" });
                }

                function tryDelete(urlIndex, methodIndex) {
                    if (urlIndex >= candidateUrls.length) {
                        return Promise.reject(new Error("delete-failed"));
                    }
                    if (methodIndex >= methods.length) {
                        return tryDelete(urlIndex + 1, 0);
                    }

                    var url = candidateUrls[urlIndex];
                    var method = methods[methodIndex];

                    return fetch(url, {
                        method: method,
                        headers: {
                            "X-CSRFToken": getCsrfToken(),
                            "X-Requested-With": "XMLHttpRequest"
                        }
                    })
                        .then(function (response) {
                            if (!response.ok && !response.redirected) {
                                return tryDelete(urlIndex, methodIndex + 1);
                            }
                            return parseResponse(response);
                        })
                        .then(function (data) {
                            if (data && data.status === "success") {
                                if (data.redirect) {
                                    window.location.href = data.redirect;
                                } else {
                                    window.location.reload();
                                }
                                return;
                            }
                            return tryDelete(urlIndex, methodIndex + 1);
                        })
                        .catch(function () {
                            return tryDelete(urlIndex, methodIndex + 1);
                        });
                }

                tryDelete(0, 0).catch(function () {
                    window.alert("Erro ao excluir o item");
                });
            });
        });
    }

    function initConfirmSubmits() {
        document.querySelectorAll("form[data-confirm-submit]").forEach(function (form) {
            if (form.dataset.confirmBound === "1") {
                return;
            }
            form.dataset.confirmBound = "1";
            form.addEventListener("submit", function (event) {
                var message = form.getAttribute("data-confirm-submit") || "Tem certeza?";
                if (!window.confirm(message)) {
                    event.preventDefault();
                }
            });
        });
    }

    function initCodigoBarrasAutoSelect() {
        var codigoBarrasInput = document.getElementById("codigo_barras");
        var produtoInput = document.getElementById("id_produto");
        if (!codigoBarrasInput || !produtoInput) {
            return;
        }

        codigoBarrasInput.addEventListener("change", function () {
            var codigo = codigoBarrasInput.value;
            if (!codigo) {
                return;
            }

            fetch("/Movimentacao/buscar-produto/?codigo_barras=" + encodeURIComponent(codigo))
                .then(function (response) { return response.json(); })
                .then(function (data) {
                    if (data.error) {
                        window.alert(data.error);
                        return;
                    }
                    produtoInput.value = data.id;
                })
                .catch(function () {})
                .finally(function () {
                    codigoBarrasInput.value = "";
                });
        });
    }

    function initVariacoesFormset() {
        var container = document.getElementById("variacoes-container");
        var addButton = document.getElementById("add-variacao");
        var totalForms = document.querySelector("#id_variacoes-TOTAL_FORMS");

        if (!container || !addButton || !totalForms || container.children.length === 0) {
            return;
        }

        addButton.addEventListener("click", function () {
            var formCount = parseInt(totalForms.value, 10);
            var newForm = container.children[0].cloneNode(true);

            newForm.querySelectorAll("input, select").forEach(function (input) {
                if (!input.name) {
                    return;
                }
                input.name = input.name.replace(/form-\d+-/, "form-" + formCount + "-");
                input.id = input.id.replace(/form-\d+-/, "form-" + formCount + "-");
                if (input.type === "checkbox") {
                    input.checked = false;
                } else if (input.type !== "hidden") {
                    input.value = "";
                }
            });

            container.appendChild(newForm);
            totalForms.value = String(formCount + 1);
        });

        container.addEventListener("click", function (event) {
            var target = event.target;
            if (!target.classList.contains("remove-variacao")) {
                return;
            }

            var form = target.closest(".variacao-form");
            if (!form) {
                return;
            }

            var deleteInput = form.querySelector('input[type="checkbox"][name$="-DELETE"]');
            if (deleteInput) {
                deleteInput.checked = true;
                form.style.display = "none";
            } else if (container.children.length > 1) {
                form.remove();
                totalForms.value = String(parseInt(totalForms.value, 10) - 1);
            }
        });
    }

    function initPortalNotifications() {
        var notifButton = document.getElementById("notif-btn");
        var notifDropdown = document.getElementById("notif-dropdown");
        var notifBadge = document.getElementById("notif-badge");
        var notifList = document.getElementById("notif-list");
        var isOpen = false;

        if (!notifButton || !notifDropdown || !notifBadge || !notifList) {
            return;
        }

        notifButton.addEventListener("click", function (event) {
            event.preventDefault();
            isOpen = !isOpen;
            notifDropdown.style.display = isOpen ? "block" : "none";
        });

        document.addEventListener("click", function (event) {
            if (!event.target.closest("#notif-btn") && !event.target.closest("#notif-dropdown")) {
                isOpen = false;
                notifDropdown.style.display = "none";
            }
        });

        function carregarNotificacoes() {
            fetch("/tickets/api/notificacoes/count/")
                .then(function (response) { return response.json(); })
                .then(function (data) {
                    if (data.count > 0) {
                        notifBadge.textContent = data.count > 99 ? "99+" : String(data.count);
                        notifBadge.style.display = "inline-flex";
                    } else {
                        notifBadge.style.display = "none";
                    }

                    if (!data.notificacoes || data.notificacoes.length === 0) {
                        notifList.innerHTML = '<div class="small text-center py-3 text-secondary">Sem notificacoes nao lidas</div>';
                        return;
                    }

                    notifList.innerHTML = data.notificacoes.map(function (notification) {
                        var mensagem = notification.mensagem ? "<div class=\"small text-secondary\">" + notification.mensagem + "</div>" : "";
                        return ""
                            + "<a href=\"" + notification.url + "\" class=\"portal-notif-item d-flex gap-2 text-decoration-none p-2 border-bottom\" data-notification-id=\"" + notification.id + "\">"
                            + "<div class=\"portal-notif-avatar rounded-circle d-flex align-items-center justify-content-center\" style=\"--notif-color:" + notification.cor + ";\">"
                            + "<i class=\"bi " + notification.icone + " portal-notif-avatar-icon\" style=\"--notif-color:" + notification.cor + ";\"></i>"
                            + "</div>"
                            + "<div><div class=\"small fw-semibold\">" + notification.titulo + "</div>"
                            + mensagem
                            + "<div class=\"small text-secondary\">" + notification.criado_em + "</div></div></a>";
                    }).join("");
                })
                .catch(function () {});
        }

        window.marcarLida = function (id) {
            fetch("/tickets/notificacoes/" + id + "/ler/", {
                method: "POST",
                headers: {
                    "X-CSRFToken": getCsrfToken(),
                    "X-Requested-With": "XMLHttpRequest"
                }
            }).then(carregarNotificacoes);
        };

        window.marcarTodasLidas = function () {
            fetch("/tickets/notificacoes/ler-todas/", {
                method: "POST",
                headers: {
                    "X-CSRFToken": getCsrfToken(),
                    "X-Requested-With": "XMLHttpRequest"
                }
            }).then(function () {
                carregarNotificacoes();
            });
        };

        notifList.addEventListener("click", function (event) {
            var link = event.target.closest(".portal-notif-item[data-notification-id]");
            if (!link) {
                return;
            }
            var id = link.getAttribute("data-notification-id");
            if (id) {
                window.marcarLida(id);
            }
        });

        var markAllButton = document.getElementById("btn-marcar-todas-lidas");
        if (markAllButton) {
            markAllButton.addEventListener("click", function () {
                window.marcarTodasLidas();
            });
        }

        carregarNotificacoes();
        window.setInterval(carregarNotificacoes, 30000);
    }

    function applyDynamicColors() {
        document.querySelectorAll(".tk-dynamic-badge, .tk-dynamic-chip, .tk-report-status-dot, .tk-notif-icon, .atv-dynamic-color").forEach(function (element) {
            var color = element.getAttribute("data-color");
            if (!color) {
                return;
            }
            element.style.setProperty("--tk-dyn-color", color);
        });
    }

    window.togglePassword = function () {
        var passwordField = document.getElementById("password");
        var toggleIcon = document.getElementById("toggleIcon");
        if (!passwordField || !toggleIcon) {
            return;
        }

        if (passwordField.type === "password") {
            passwordField.type = "text";
            toggleIcon.classList.remove("fa-eye");
            toggleIcon.classList.add("fa-eye-slash");
        } else {
            passwordField.type = "password";
            toggleIcon.classList.remove("fa-eye-slash");
            toggleIcon.classList.add("fa-eye");
        }
    };

    document.addEventListener("DOMContentLoaded", function () {
        initTheme();
        markActiveSidebarLink();
        initSubmenuToggles();
        initNotificationDropdown();
        initDeleteButtons();
        initConfirmSubmits();
        initCodigoBarrasAutoSelect();
        initVariacoesFormset();
        initPortalNotifications();
        applyDynamicColors();
    });
})();
