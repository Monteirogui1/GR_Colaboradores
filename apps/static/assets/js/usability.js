document.addEventListener('DOMContentLoaded', function () {
    // Inicializar tooltips
    const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    tooltipTriggerList.forEach(tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl));

    // Validação em tempo real para número do lote
    const loteForm = document.getElementById('loteForm');
    if (loteForm) {
        const numeroLoteInput = loteForm.querySelector('input[name="numero_lote"]');
        numeroLoteInput.addEventListener('input', async function () {
            const value = this.value.trim();
            if (value.length > 0) {
                const response = await fetch(`/movimentacao/lote/validar-numero/?numero_lote=${encodeURIComponent(value)}`);
                const data = await response.json();
                const feedback = numeroLoteInput.nextElementSibling || document.createElement('div');
                feedback.className = 'form-text';
                if (data.exists) {
                    feedback.className = 'text-danger';
                    feedback.textContent = 'Este número de lote já está em uso.';
                } else {
                    feedback.className = 'text-success';
                    feedback.textContent = 'Número de lote disponível.';
                }
                if (!numeroLoteInput.nextElementSibling) {
                    numeroLoteInput.parentNode.appendChild(feedback);
                }
            }
        });
    }

    // Busca AJAX
    const searchForm = document.getElementById('searchForm');
    if (searchForm) {
        const searchInput = searchForm.querySelector('input[name="q"]');
        if (searchInput) {
            const searchResults = document.createElement('div');
            searchResults.className = 'search-results dropdown-menu';
            searchForm.appendChild(searchResults);

            searchInput.addEventListener('input', async function () {
                const query = this.value.trim();
                if (query.length < 3) {
                    searchResults.innerHTML = '';
                    searchResults.style.display = 'none';
                    return;
                }

                const response = await fetch(`/home/search/?q=${encodeURIComponent(query)}`);
                const data = await response.json();
                searchResults.innerHTML = '';
                if (data.results.length === 0) {
                    searchResults.innerHTML = '<div class="dropdown-item">Nenhum resultado encontrado</div>';
                } else {
                    data.results.forEach(result => {
                        const item = document.createElement('a');
                        item.className = 'dropdown-item';
                        item.href = result.url;
                        item.textContent = result.nome;
                        searchResults.appendChild(item);
                    });
                }
                searchResults.style.display = 'block';
            });

            // Fechar resultados ao clicar fora
            document.addEventListener('click', function (e) {
                if (!searchForm.contains(e.target)) {
                    searchResults.style.display = 'none';
                }
            });
        }
    }
});
