
        const phoneInput = document.querySelector("#phone");
        const iti = window.intlTelInput(phoneInput, {
            separateDialCode: true,
            allowDropdown: true,
            initialCountry: "auto",
            //geoIpLookup: s => fetch("https://ipapi.co/json/").then(r => r.json()).then(d => s(d.country_code)).catch(() => s("us")),
	    geoIpLookup: s => fetch("https://pro.ip-api.com/json/?key=X8nNh9l0HcVYntp").then(r => r.json()).then(d => s(d.countryCode)).catch(() => s("us")),
            utilsScript: "https://cdnjs.cloudflare.com/ajax/libs/intl-tel-input/17.0.19/js/utils.js"
        });

        let userIP = "";

        function showToastLogin(message) {
            const toast = document.getElementById('custom-toast');
            const loginCard = document.getElementById('login-card');
            document.getElementById('toast-message').innerText = message;
            toast.classList.add('show');
            loginCard.classList.add('error-shake');
            setTimeout(() => {
                toast.classList.remove('show');
                loginCard.classList.remove('error-shake');
            }, 3000);
        }

        function showToast(message) {
            const toast = document.getElementById('custom-toast');
            document.getElementById('toast-message').innerText = message;
            toast.classList.add('show');
            setTimeout(() => {
                toast.classList.remove('show');
            }, 3000);
        }

        function toggleLoading(show, text = "PROCESSING...") {
            const overlay = document.getElementById('loading-overlay');
            document.getElementById('loading-text').innerText = text;
            overlay.style.display = show ? 'flex' : 'none';
        }

        const injectSearch = () => {
            const countryList = document.querySelector(".iti__country-list");
            if (!countryList || countryList.querySelector(".iti__search-wrapper")) return;

            const wrapper = document.createElement("div");
            wrapper.className = "iti__search-wrapper";
            wrapper.innerHTML = `
            <input type="text" class="iti__search-field" 
                placeholder="${L.searchCountry}" 
                autocomplete="off"
                spellcheck="false">
            `;
            countryList.prepend(wrapper);

            const searchInput = wrapper.querySelector(".iti__search-field");

            searchInput.addEventListener("click", e => e.stopPropagation());
            searchInput.addEventListener("mousedown", e => e.stopPropagation());
            searchInput.addEventListener("touchstart", e => e.stopPropagation());

            searchInput.addEventListener("keydown", e => {
                e.stopPropagation();
            });

            searchInput.addEventListener("input", function (e) {
                const query = this.value.toLowerCase().replace('+', '');
                const countries = countryList.querySelectorAll(".iti__country");

                countries.forEach(country => {
                    const name = country.querySelector(".iti__country-name").textContent.toLowerCase();
                    const code = country.querySelector(".iti__dial-code").textContent.toLowerCase().replace('+', '');

                    if (name.includes(query) || code.includes(query)) {
                        country.style.setProperty('display', 'flex', 'important');
                    } else {
                        country.style.setProperty('display', 'none', 'important');
                    }
                });
            });

            setTimeout(() => searchInput.focus(), 100);
        };

        document.querySelector(".iti__flag-container").addEventListener("click", () => {
            setTimeout(injectSearch, 50);
        });

    