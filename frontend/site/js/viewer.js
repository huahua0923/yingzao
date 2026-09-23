// 交付件 GLB 的查看器 —— 前台的三维那一半。
//
// 为什么直接看 GLB、不照 building.html 那 2332 行现搭几何：
//   1. 后端已经在发**交付件本身**（/api/buildings/<楼>/model.glb），前台看真交付物
//      比看一份现场重算的近似更可信 —— 屏幕上是什么，交付的就是什么。
//   2. 重构方案把那 2332 行的迁移列为"风险最高"（要求像素回归 <0.5%），
//      而这条路的回归面只有"GLB 能不能显示"。
//
// 朝向约定**照抄仓内既有的 render_j6.html**（那是已经能出图的查看器）：
// GLB 按导出原样用，Y 轴朝上，**不施加任何旋转**，只做 Box3 居中再按包围盒套相机。
// 自己猜轴会得到一栋躺着的楼，而"躺着"和"参数不对"在屏幕上长得一样。
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const BG = 0xece7de;        // 与 site.css 的 --paper-sink 同一个色：三维也算在"图纸底板"上

export function createViewer(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setClearColor(BG, 1);
  renderer.shadowMap.enabled = true;
  // ★ 别用 PCFSoftShadowMap —— 0.185.1 已废弃，渲染器会在第一帧把它改成 PCFShadowMap
  //   并往 console 打一条 warn（也就是"我写的枚举根本没生效，只是它替我改对了"）。
  //   柔边靠 shadow.radius：PCF 分支的 getShadow 拿它做 5 抽 Vogel 盘
  //   （sampler 源码 shadowmap_pars_fragment 里 radius = shadowRadius * texelSize.x）。
  renderer.shadowMap.type = THREE.PCFShadowMap;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.5, 20000);

  // 光照配色跟随纸面基调（暖主光 + 冷补光），不是纯白 —— 纯白会把
  // 白色墙体打成一片没有转折的平板，看不出体量。
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8c8578, 1.15));
  const sun = new THREE.DirectionalLight(0xfff4e2, 2.2);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  scene.add(sun);
  const fill = new THREE.DirectionalLight(0xdce6f2, 0.55);
  fill.position.set(-180, 90, -140);
  scene.add(fill);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  // 不让相机钻到地面以下：地平面以下看到的是一栋楼的内侧，纯误导。
  controls.maxPolarAngle = Math.PI / 2 - 0.02;
  controls.minDistance = 5;

  let model = null;
  let ground = null;
  let raf = 0;

  /** 画布尺寸跟随父元素（不是 window）—— 页面里画布只占中间那块舞台。 */
  function resize() {
    const box = renderer.domElement.parentElement?.getBoundingClientRect();
    const w = Math.max(1, Math.floor(box?.width ?? 1));
    const h = Math.max(1, Math.floor(box?.height ?? 1));
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(resize);
  if (renderer.domElement.parentElement) ro.observe(renderer.domElement.parentElement);

  function frame(box) {
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z) || 1;

    // 相机方向固定为等轴测那一路（1, 0.8, 1）—— 建筑看体量就该斜着看。
    const dir = new THREE.Vector3(1, 0.8, 1).normalize();
    const dist = maxDim * 1.75;
    camera.position.copy(center).addScaledVector(dir, dist);
    camera.near = Math.max(0.5, maxDim / 500);
    camera.far = dist * 8;
    camera.updateProjectionMatrix();
    controls.target.copy(center);
    controls.update();

    // 阴影相机跟着包围盒收紧：默认的正交范围太大，阴影会糊成一团。
    sun.position.copy(center).add(new THREE.Vector3(maxDim, maxDim * 1.6, maxDim));
    sun.target.position.copy(center);
    sun.target.updateMatrixWorld();
    const r = maxDim * 0.85;
    const sc = sun.shadow.camera;
    sc.left = -r; sc.right = r; sc.top = r; sc.bottom = -r;
    sc.near = maxDim * 0.1; sc.far = maxDim * 5;
    sc.updateProjectionMatrix();
    sun.shadow.bias = -0.0015 * (maxDim / 100);
    sun.shadow.radius = 3;                      // 柔边。PCF 分支真的读它（见文件头的说明）
    sun.shadow.normalBias = maxDim * 0.0015;    // 按法线推一点采样点：比只调 bias 少一点"影子跟墙脱开"
  }

  function clearModel() {
    if (!model) return;
    scene.remove(model);
    // 几何/材质要显式 dispose：浏览器 Tab 开久了会攒住显存，
    // 而"看下一栋"这个动作会把这件事重复很多次。
    model.traverse((o) => {
      if (!o.isMesh) return;
      o.geometry?.dispose?.();
      const m = o.material;
      if (Array.isArray(m)) m.forEach((x) => x.dispose?.());
      else m?.dispose?.();
    });
    model = null;
  }

  /** 载入一个 GLB。onProgress 收 (已载字节, 总字节|null)。 */
  function load(url, onProgress) {
    clearModel();
    if (ground) { scene.remove(ground); ground.geometry.dispose(); ground = null; }
    controls.autoRotate = false;

    const loader = new GLTFLoader();
    return loader.loadAsync(url, (ev) => {
      onProgress?.(ev.loaded, ev.total || null);
    }).then((gltf) => {
      const m = gltf.scene;
      let tris = 0;
      m.traverse((o) => {
        if (!o.isMesh) return;
        o.castShadow = true;
        o.receiveShadow = true;
        const g = o.geometry;
        tris += g.index ? g.index.count / 3 : (g.attributes.position?.count ?? 0) / 3;
      });

      const box = new THREE.Box3().setFromObject(m);
      if (box.isEmpty()) {
        throw new Error('GLB 里没有任何可显示的网格（bbox 是空的）');
      }
      // 居中到原点：GLB 里带的是 CAD 世界坐标（百万量级），
      // 不居中的话 float32 精度会把面片抖成一团。
      const c = box.getCenter(new THREE.Vector3());
      m.position.sub(c);
      scene.add(m);
      model = m;

      const b2 = new THREE.Box3().setFromObject(m);
      const size = b2.getSize(new THREE.Vector3());
      // 地面：只是给个"楼立在地上"的参照，不留影子的方向歧义。
      const gr = new THREE.Mesh(
        new THREE.PlaneGeometry(Math.max(size.x, size.z) * 3, Math.max(size.x, size.z) * 3),
        new THREE.ShadowMaterial({ opacity: 0.16 }));
      gr.rotation.x = -Math.PI / 2;
      gr.position.y = b2.min.y;
      gr.receiveShadow = true;
      scene.add(gr);
      ground = gr;

      frame(b2);
      resize();
      // 回普通数值，不回 THREE 对象：页面层不该为了打印一行尺寸
      // 去 import three（那也会把 three 拖进首屏的解析路径）。
      return {
        triangles: Math.round(tris),
        size: { x: size.x, y: size.y, z: size.z },
        center: { x: c.x, y: c.y, z: c.z },
      };
    });
  }

  function start() {
    if (raf) return;
    const tick = () => { raf = requestAnimationFrame(tick); controls.update(); renderer.render(scene, camera); };
    tick();
  }
  function stop() { if (raf) { cancelAnimationFrame(raf); raf = 0; } }

  /** 切页面时必须收干净：rAF 还在跑的话，WebGL 上下文会一直占着。 */
  function dispose() {
    stop();
    ro.disconnect();
    controls.dispose();
    clearModel();
    if (ground) { ground.geometry.dispose(); ground.material.dispose(); ground = null; }
    renderer.dispose();
  }

  return { load, start, stop, dispose, resize,
           refit: () => { if (model) frame(new THREE.Box3().setFromObject(model)); } };
}
