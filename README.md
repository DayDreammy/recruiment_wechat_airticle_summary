# Pandora 微信文章采集总结

自动化采集微信公众号文章并总结展示。

1. 使用quicker模拟键鼠操作批量获取公众号文章链接
2. 使用开源项目[wechatDownload](https://github.com/xiaoguyu/wechatDownload)下载文章
3. 使用LLM总结文章

## 使用quicker模拟键鼠操作获取公众号文章链接

quicker动作地址 ： [获取公众号文章链接 - by 123yy123 - 动作信息 - Quicker (getquicker.net)](https://getquicker.net/Sharedaction?code=804e8748-a95d-43bd-402d-08dc41766143)

video:
![getlink.mp4](README.assets/getlink.gif)

输出：
![links.txt](README.assets/links.png)

目前只适配了 2560×1440 的屏幕，存在一些鼠标固定坐标，别的尺寸屏幕需要自己调整下。

完整的动作地址：[自动采集总结公众号文章 - by 123yy123 - 动作信息 - Quicker (getquicker.net)](https://getquicker.net/Sharedaction?code=a5ed830b-e2fa-444a-402e-08dc41766143)

![getarticle.gif](README.assets/getarticle.gif)

输出：
![airtle_files](README.assets/airtle_files.png)

每天定时运行即可实现微信公众号文章监控+采集，也就是公众号RSS。（目前全文只存在了本地，没有接入RSS服务，后续会接入）

## Use Case

1. [Pandora 招聘信息分享 jobs.daydreammy.xyz](https://jobs.daydreammy.xyz)

   截至24.03.28

   ![image-20240328011512812](README.assets/image-20240328011512812-17115597165961.png)

## 写在后面

1. shi山代码refactor，拖延了开源进度，然shi上雕花尔；
2. 最高级的反爬机制往往采用最朴素的方式，这样的Human-like ”爬虫“ 微信大概是防不了的；
3. 第一次学着写 quicker 动作，有的鼠标坐标是写死的，希望后面可以改进；
4. pdfsummary操作目前也是比较朴素，实际上是接入了MySQL的，但是目前只是文件操作；
5. 水平有限，后面学着怎么接入更大的RSS项目；
6. 当模型结构一样，数据集水平决定模型上限，私以为人也是这样，信息输入很大程度塑造了”人“；
7. 终极愿景是让信息更加顺畅的流动 + 有个秘书帮忙处理过载信息：
   1. 多样信息源，一些新闻网站、播客、微信公众号、博客、bilibili视频等，都可以总结摘要（也就是RSS）；
   2. 这样可以花比较少的时间去关注更值得的信息。