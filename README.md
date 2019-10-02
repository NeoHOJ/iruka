# <ruby>I<rt>イ</rt>ru<rt>ル</rt>ka<rt>カ</rt></ruby>

> 🐬 イルカ: The worker of NeoHOJ backend.\
> 🐬 イルカ: NeoHOJ 後端的勞務提供者 (這什麼翻譯)。


This is a judge client responsible for building and securely running user's submitted code.

這是一個評測系統的客戶端，負責建置及安全地執行使用者上傳的程式碼。

## Overview (概觀)

Roughly, it communicates with the server (called Iruka Server for now) with gRPC. authenticating with an token, and start "listening" [1] for the server's request. Sound strange but this structure is advantageous as we dive in later. Upon receiving a judging request, the client first decides if it can handle this request by e.g., checking request validity or test data intergrity. If the answer is yes, it starts a so-called "pipeline" (in CI, of course). After compiling the code, running the resulted program, validating the answer, the clients determine some statistics and the verdict like `AC` or `WA` and send it back to the server by initiating another connection.

大致上來說，它和伺服器端 (現在叫做 Iruka Server，~之後應該會取個獨立的名字啦~) 用 gRPC 溝通，用權杖 (token) 來和伺服器驗證身份，並且開始「聽」 [1] 伺服器端的請求。這個架構聽起來超奇怪的對吧，但它有些優勢是之後深入理解之後才會看出來的。一旦收到一個評測請求，它會先檢查自己是否有足夠的條件評測，像是檢查請求的合法性或是測資是否齊備。如果是的話就會啟動一個管線機制 (當然，這裡是說 CI 的那個 pipeline)。程式碼經過編譯、執行、確認答案等階段之後會得到統計資料和評測的狀態像是 `AC` 或 `WA` 等等，然後客戶端對伺服器端開啟另一個請求把這些資料送回。


By strictly separating out the server/client, we can prevent a malicious client messing up the database or corrupt the test data. This design is also scalable as the client need not worry about how to poll the database, how to receive the dataset from the wire, etc., and the server can have a better control of scheduling.

藉由明確切分伺服端和客戶端的設計，我們可以避免惡意的客戶端弄炸資料庫或毀損測資。這個設計也比較好擴容，因為客戶端不需要為如何輪詢資料庫或如何反序列化測試資料集等等而困擾，而且伺服器端也比較能控制排程。


[1]: "server-side streaming" in HTTP/2, can be thought as long-polling in HTTP 1.x
     用 HTTP/2 的術語叫做「伺服器端串流」，可以想成是 HTTP 1.x 的 long-polling。

## Deploying (如何部署)

You should have `pipenv` installed. `pyenv` is optional but preferred for installing the recommended version of Python.

```bash
pipenv install
pipenv shell
```

Copy configurations:

```bash
cp iruka.yml{.example,}
```

Don't forget to edit it.

Generate protobuf bindings/grpc stubs:

```bash
scripts/gen_protos.py
```

Then you are all set.

```bash
# after each reboot you need to do this step to initialize control groups... edit it before proceed!
bin/cgroups_init.sh

# run as your current user
python -m iruka
# or preferrably, run as another user
sudo -u nobody $(pipenv --venv)/bin/python -m iruka
```

這部分懶得翻譯ㄌ

## Help wanted (想要有人幫忙)

As this project is in very early stage of development, don't hestitate if you can contribute to it. My time budget on this project is tight, but I am really eager to build a judging system that is generic and secure enough. From making reasonable suggestions to inventing some new features, your help is greatly appreciated.

## Reference (參考資料)

這個評測系統參考了下列開源軟體的實作 (未依任何方式排序)：

- judgeGirl's judge-receiver
- google/nsjail
- cms-dev/isolate
- QindaoU judge server
- Kattis problem format ([translated](https://github.com/cebrusfs/kattis-examples/blob/master/PROBLEM-SPEC.md))
- [DMOJ/judge](https://github.com/DMOJ/judge)
