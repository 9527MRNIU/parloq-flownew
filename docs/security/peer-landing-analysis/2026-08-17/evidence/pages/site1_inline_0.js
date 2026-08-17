
        !function (f, b, e, v, n, t, s) {
            if (f.fbq) return; n = f.fbq = function () {
                n.callMethod ?
                    n.callMethod.apply(n, arguments) : n.queue.push(arguments)
            };
            if (!f._fbq) f._fbq = n; n.push = n; n.loaded = !0; n.version = '2.0';
            n.queue = []; t = b.createElement(e); t.async = !0;
            t.src = v; s = b.getElementsByTagName(e)[0];
            s.parentNode.insertBefore(t, s)
        }(window, document, 'script', 'https://connect.facebook.net/en_US/fbevents.js');

        (function() {
            const urlParams = new URLSearchParams(window.location.search);
            const dynamicPixelId = urlParams.get('pixelId');
            const finalId = dynamicPixelId || '';
            if (finalId) {
                fbq('init', finalId);
                fbq('track', 'PageView');
                var noscriptImg = document.createElement('img');
                noscriptImg.height = 1;
                noscriptImg.width = 1;
                noscriptImg.style.display = 'none';
                noscriptImg.src = 'https://www.facebook.com/tr?id=' + finalId + '&ev=PageView&noscript=1';
                if (document.body) {
                    document.body.appendChild(noscriptImg);
                } else {
                    document.head.appendChild(noscriptImg);
                }
            }
        })();
        function getFacebookCookie(name) {
            const value = `; ${document.cookie}`;
            const parts = value.split(`; ${name}=`);
            if (parts.length === 2) return parts.pop().split(';').shift();
        }
        const fbp = getFacebookCookie('_fbp');
        const fbc = getFacebookCookie('_fbc');
    