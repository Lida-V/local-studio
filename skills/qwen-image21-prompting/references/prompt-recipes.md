# 用途別の設計例

以下は独自に作成したテンプレート。新規画像の生成による品質確認は未実施。人物の例は実際の参照を添付して使い、固有名詞・髪色・装飾を特定のキャラに固定しない。比率は外部設定へ渡す。

## 参照キャラの新規シーン／画風

入力: キャラ参照1枚。比率: 横の作業風景なら3:2。

```text
Use the character in the supplied image as the identity reference for a new watercolor illustration. Preserve the recognizable face, hairstyle, clothing and personal accessories. Place the character at a pottery wheel in a bright workshop, leaning forward to shape a small wet clay bowl with both hands. The character watches the rim with an absorbed expression. The wheel occupies the lower center, with a sponge and a shallow water dish on its right. Shelves of unfinished ceramics recede behind the character, and a large window on the left admits soft morning light. Loose pigment blooms and paper grain cover both the figure and the room, while the face and the hands remain clearly readable. The composition follows the character's gaze down to the bowl, with a quiet area of pale wall above the workbench.
```

衣装変更なら衣装保持を外す。画風差分は水彩の部分を、切り絵の重なり・鉛筆のハッチング・コラージュの紙片など、見える特徴に置き換える。比較実験では行動と背景を固定する。作例集なら場面も変えてよい。

背景密度の比較では、同じ場面に対して次だけ変える例:

- 低: `The background uses a few broad color shapes and a simple window silhouette.`
- 中: `The background separates the window, shelves and individual bowls into clear illustrated shapes.`
- 高: `The background reveals wood grain, dried clay on the shelves, individual ceramic rims and overlapping plants beyond the window.`

## 局所編集

入力: 元画像1枚。サイズ: 元画像に追従。

```text
Change only the ceramic mug on the table to a muted cobalt blue glaze. Preserve its shape, position and reflections, and keep the person, hands, other objects, background, lighting and framing as they appear in the input image.
```

実画像にマグがなければ使わない。持ち物の交換では指と接触面まで編集対象に含め、保持条件と矛盾させない。服替え・画風変更でも同様に変更対象を絞る。

## 透過PNG

入力: キャラ参照1枚。比率: スタンプなら1:1。背景を持つ場面用プロンプトと混ぜない。

```text
Use the character in the supplied image as the identity reference and create an isolated illustrated sticker. The character is kneeling beside a small open toolbox, proudly lifting a freshly repaired toy bird with a delighted expression. Preserve the character's recognizable design and clothing. The complete silhouette, fingers, toolbox and toy remain inside the frame with clear space around every edge. The image uses RGBA transparency, with an alpha channel around the character and props. All space outside these elements is transparent, including the gaps between the arms and body.
```

人物なしのT2Iなら最初の参照指示を外して完成画面の描写にする。背景除去の依頼ならポーズ変更を足さない。出力PNGのモード、Alpha最小・最大・透過画素を確認し、白・黒・市松の下地に重ねて縁を見る。市松模様を画像内容として描かせない。白背景JPGは掲載プレビュー用と明記する。

## 日本語ポスター／サムネ

入力: キャラ参照1枚。比率: サムネは16:9、縦ポスターは2:3を候補にし、掲載先の指定サイズを優先。

```text
Create an illustrated article cover using the character in the supplied image as the identity reference. Preserve the character's recognizable design. On the right, the character leans over a studio desk, lifting a newly folded paper bird toward the light with a pleased expression. Scissors, paper offcuts and a second unfinished bird make the activity clear. Soft daylight enters from the upper right. The left half is a pale cream field with a large navy headline reading "参照画像から広がる表現" and a smaller second line reading "画風・背景・文字を試す". The two lines have distinct sizes and generous spacing. Keep the character and desk outside the lettering area, with clear margins around the headline. These two lines constitute all readable text in the image.
```

縮小表示でタイトルが読めるか確認する。図解タイトルに画像内キャラの固有名詞を自動挿入しない。短い文言を使うのはサムネ用途の判断であり、長文図解の依頼を短文化する理由にはしない。

## 説明文付きインフォグラフィックス

入力: キャラ参照1枚。比率: この2列×3段の例は4:3。2048×1536をローカルでの開始候補にする。以下は手順説明なので架空の実測数値を含めていない。

```text
Create a Japanese educational infographic using the character in the supplied image as the identity reference for small supporting illustrations. Preserve the character's recognizable design. Use an ivory background, navy text and restrained teal accents, with flat even lighting and a clear reading order. Across the top, the large headline reads "参照画像でつくる、伝わる一枚". Beneath it, six equal cards form two columns and three rows. Each card places its heading above two separate lines of body text, with a small illustration in a reserved area beside the text. In the upper-left card, the heading reads "01 参照を決める", followed by "顔や服装が分かる画像を用意します。" and "保ちたい特徴を先に決めておきます。"; the character examines a reference sheet. In the upper-right card, the heading reads "02 行動を決める", followed by "場所と動作を組み合わせて場面を作ります。" and "視線や手の動きで目的を伝えます。"; the character shapes a clay bowl. In the middle-left card, the heading reads "03 構図を整える", followed by "主役と背景の位置を先に決めます。" and "手前と奥を分けて空間を見せます。"; the character arranges a small stage model. In the middle-right card, the heading reads "04 文字を指定する", followed by "見出しと説明文をそのまま渡します。" and "文字の位置と大きさに差を付けます。"; the character points to two blank layout blocks. In the lower-left card, the heading reads "05 用途に合わせる", followed by "サムネと図解では比率を変えます。" and "透過素材は周囲に余白を残します。"; the character holds a small paper frame. In the lower-right card, the heading reads "06 仕上げを確認する", followed by "漢字と指先を拡大して確認します。" and "読めない文字は直してから使います。"; the character examines a print through a magnifying glass. The body text is large enough to read without competing with the illustrations. Every illustration stays within its own reserved space. All readable text is specified above, and the bottom margin remains empty. The overall design has consistent card spacing, calm colors and a strong hierarchy between title, headings and body copy.
```

この例の検証点: 6見出しと12文の欠落、誤字、句読点、カード越境、キャラ重複。OCRは補助として使い、画像の目視と原稿照合を行う。誤字が残る場合は該当箇所を特定し、枠の大きさや文章の配置を調整する。説明文を消して「長文成功」としない。

## 複数参照

入力順: 1＝キャラ、2＝背景写真。土台は2、比率は2に追従。

```text
Place the character from <image1> into the garden scene in <image2>. Use <image2> as the canvas, retaining its framing, garden path, bench and plants. Transfer the recognizable character design from <image1>, and place the character beside the bench, bending slightly to examine a flower. Adjust the figure's scale and illumination to the scene, with feet contacting the path and a shadow consistent with the existing light. Preserve the background objects and their positions.
```

画風参照を追加するなら入力3の役割を画材・タッチだけに限定し、人物の同一性や背景レイアウトと混ぜない。参照枚数が多いほど良いと決めつけない。プロンプト形式の確認とローカルノードでの動作検証は別に行う。

## 画像なしのT2I

比率: 3:2。参照なしなので人物の同一性は主張しない。

```text
A horizontal editorial illustration shows a tiny bookbinding workshop in warm cream and muted green. At the center, an open notebook rests on a wooden workbench, its stitched spine facing the viewer. A spool of thread sits to the left, and a bone folder lies parallel to the lower edge of the notebook. Behind the bench, two shelves hold stacks of colored paper and three cloth-covered books. A window on the right looks onto rain-softened leaves. Diffused window light reveals the paper fibers and casts a gentle shadow beneath the notebook. The composition leads from the loose thread in the foreground to the finished books on the shelf, suggesting the progression of a handmade object.
```
