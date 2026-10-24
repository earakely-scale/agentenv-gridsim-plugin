import * as THREE from "three";

const smooth = (a, b, x) => {
  const u = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return u * u * (3 - 2 * u);
};

/** The cold front's shelf cloud: a dark wall on the horizon the front comes from, rising over the hours before it
 * passes (p 0..1) with a lit, ragged leading edge, gone once the front is through and the observed sky takes over. */
export function buildFront(radius = 58000) {
  const mat = new THREE.ShaderMaterial({
    side: THREE.BackSide, transparent: true, depthWrite: false, fog: false,
    uniforms: {
      uP: { value: 0 }, uDir: { value: new THREE.Vector2(0, -1) }, uSun: { value: new THREE.Vector3(0, 1, 0) }, uSunCol: { value: new THREE.Color() },
      uDay: { value: 1 }, uNight: { value: 0 }, uHaze: { value: new THREE.Color() }, uTime: { value: 0 }, uA: { value: 0 },
    },
    vertexShader: /* glsl */ `
      varying vec3 vDir;
      void main() {
        vDir = normalize(position);
        vec4 p = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        gl_Position = p.xyww;
      }`,
    fragmentShader: /* glsl */ `
      uniform vec3 uSun, uSunCol, uHaze;
      uniform vec2 uDir;
      uniform float uP, uDay, uNight, uTime, uA;
      varying vec3 vDir;
      float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
      float noise(vec2 p) {
        vec2 i = floor(p), f = fract(p);
        vec2 u = f * f * (3.0 - 2.0 * f);
        return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y);
      }
      float fbm(vec2 p) {
        float v = 0.0, a = 0.5;
        for (int k = 0; k < 5; k++) { v += a * noise(p); p = p * 2.03 + vec2(11.0, 7.0); a *= 0.5; }
        return v;
      }
      void main() {
        vec3 d = normalize(vDir);
        float h = d.y;
        if (h < -0.02 || uA <= 0.0) discard;
        vec2 hz = normalize(d.xz + 1e-5);
        float al = dot(hz, normalize(uDir));
        float az = atan(hz.y, hz.x);
        float span = smoothstep(-0.45, 0.35, al);
        float p = pow(uP, 1.5);
        float arc = 0.3 + 0.7 * smoothstep(-0.45, 1.0, al);
        float top = mix(0.02, 0.58, p) * arc;
        float base = mix(0.004, 0.035, p) * arc;
        float wave = (noise(vec2(az * 2.2, 1.0)) - 0.5) * 0.35 + (fbm(vec2(az * 9.0 + uTime * 0.003, 4.0)) - 0.5) * 0.18;
        float edge = top * (1.0 + wave);
        float body = (1.0 - smoothstep(edge - 0.012 - 0.02 * p, edge + 0.004, h)) * smoothstep(base - 0.004, base + 0.006, h);
        float r = clamp((h - base) / max(0.004, edge - base), 0.0, 1.0);
        vec2 q = vec2(az * 5.0, h * 60.0 / (0.25 + p));
        float tex = fbm(q + vec2(uTime * 0.006, 0.0));
        float scud = fbm(vec2(az * 11.0 + uTime * 0.01, h * 140.0 / (0.25 + p)));
        float shelfR = r + (tex - 0.5) * 0.18;
        float tier = smoothstep(0.55, 0.75, shelfR) * (1.0 - smoothstep(0.8, 0.95, shelfR));
        float capR = smoothstep(0.86, 1.0, shelfR);
        vec3 sd = normalize(uSun);
        float lit = clamp(dot(normalize(vec3(uDir.x, 0.35, uDir.y)), sd) * 0.5 + 0.5, 0.0, 1.0) * step(-0.05, sd.y);
        vec3 under = mix(vec3(0.13, 0.145, 0.17), vec3(0.22, 0.24, 0.28), scud * 0.8 + r * 0.25);
        vec3 shelf = mix(vec3(0.3, 0.33, 0.37), vec3(0.4, 0.43, 0.47), tex);
        vec3 cap = mix(vec3(0.46, 0.49, 0.53), vec3(0.58, 0.6, 0.63) + uSunCol * 0.06, lit);
        vec3 col = mix(under, shelf, tier * 0.55);
        col = mix(col, cap, capR * 0.7);
        col *= 0.2 + 0.8 * uDay;
        col = mix(col, vec3(0.025, 0.03, 0.04) + vec3(0.05, 0.035, 0.025) * smoothstep(0.3, 0.0, r), uNight * 0.9);
        col = mix(col, uHaze, (1.0 - smoothstep(0.0, 0.04 + 0.05 * (1.0 - p), h)) * 0.55);
        float a = body * span * uA * (0.86 + 0.14 * tex);
        float slot = smoothstep(0.0, base, h) * (1.0 - smoothstep(base, base + 0.01, h)) * span * uA * uDay;
        col = mix(col, uHaze * 1.08, slot * (1.0 - body));
        a = max(a, slot * 0.3);
        gl_FragColor = vec4(col, a);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  });
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(radius, 96, 48), mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = -8;
  const U = mat.uniforms;
  return {
    mesh,
    /** p: progress of the front toward the site (0 far, 1 passing); bearing it comes from, degrees from north. */
    update({ p, bearing, s, wall, reduced }) {
      const a = p <= 0 ? 0 : smooth(0, 0.12, p) * (1 - smooth(1.0, 1.18, p));
      U.uA.value = a;
      mesh.visible = a > 0.002;
      if (!mesh.visible) return 0;
      U.uP.value = Math.min(1, p);
      const b = (bearing * Math.PI) / 180;
      U.uDir.value.set(Math.sin(b), -Math.cos(b));
      U.uSun.value.copy(s.sunDir);
      U.uSunCol.value.setHSL(0.08, 0.5, 0.6);
      U.uDay.value = s.day;
      U.uNight.value = s.night;
      U.uHaze.value.copy(s.haze);
      U.uTime.value = reduced ? 0 : wall;
      const sb = Math.atan2(s.sunDir.x, -s.sunDir.z);
      const toward = Math.max(0, Math.cos(sb - b));
      const top = 0.02 + 0.56 * Math.pow(Math.min(1, p), 1.5);
      return a * smooth(0.3, 0.9, toward) * (s.sunDir.y < top ? 1 : 0.3);
    },
  };
}

/** Frost or glaze on a panel's glass (uFrost 0..1): crystalline, matte and pale, patchy as it starts and as it melts. */
export function frostOn(mat, U) {
  if (mat.userData.frost) return mat;
  mat.userData.frost = true;
  const prev = mat.onBeforeCompile;
  const base = mat.customProgramCacheKey();
  mat.onBeforeCompile = (sh, r) => {
    prev?.call(mat, sh, r);
    sh.uniforms.uFrost = U.uFrost;
    sh.fragmentShader = "uniform float uFrost;\nfloat frH(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }\n" + sh.fragmentShader
      .replace("#include <map_fragment>", `#include <map_fragment>
        float frostCov = 0.0;
        {
          vec2 q = vMapUv * vec2(1.0, 14.0);
          vec2 c = floor(q * 9.0);
          float n = frH(c), m = frH(floor(q * 2.3) + 17.0);
          frostCov = smoothstep(0.08, 0.55, uFrost + (m - 0.5) * 0.45 + (n - 0.5) * 0.12) * step(0.001, uFrost);
          float fe = frH(floor(q * vec2(31.0, 23.0)) + 5.0);
          vec3 ice = mix(vec3(0.62, 0.68, 0.76), vec3(0.9, 0.93, 0.96), n * 0.6 + fe * 0.4);
          diffuseColor.rgb = mix(diffuseColor.rgb, ice, frostCov * (0.62 + 0.2 * fe));
        }`)
      .replace("#include <roughnessmap_fragment>", "#include <roughnessmap_fragment>\nroughnessFactor = mix(roughnessFactor, 0.82, frostCov);");
  };
  mat.customProgramCacheKey = () => `${base}-frost`;
  return mat;
}

/** Snow lying on upward faces (uSnowD 0..1, patchy where it is thin) and rime on the ground (uRime), in world space so
 * it lies in drifts across the site rather than as a wash. */
export function coverOn(mat, U, rime = true) {
  if (mat.userData.cover) return mat;
  mat.userData.cover = true;
  const prev = mat.onBeforeCompile;
  const base = mat.customProgramCacheKey();
  mat.onBeforeCompile = (sh, r) => {
    prev?.call(mat, sh, r);
    sh.uniforms.uSnowD = U.uSnowD;
    sh.uniforms.uRime = U.uRime;
    sh.vertexShader = "varying vec3 vCovW;\n" + sh.vertexShader.replace("#include <project_vertex>", `#include <project_vertex>
      {
        vec4 cw = vec4(transformed, 1.0);
        #ifdef USE_INSTANCING
        cw = instanceMatrix * cw;
        #endif
        vCovW = (modelMatrix * cw).xyz;
      }`);
    sh.fragmentShader = `uniform float uSnowD, uRime;
      varying vec3 vCovW;
      float cvH(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
      float cvN(vec2 p) {
        vec2 i = floor(p), f = fract(p);
        vec2 u = f * f * (3.0 - 2.0 * f);
        return mix(mix(cvH(i), cvH(i + vec2(1, 0)), u.x), mix(cvH(i + vec2(0, 1)), cvH(i + vec2(1, 1)), u.x), u.y);
      }
` + sh.fragmentShader.replace("#include <normal_fragment_maps>", `#include <normal_fragment_maps>
      if (uSnowD + uRime > 0.001) {
        float up = dot(normal, normalize((viewMatrix * vec4(0.0, 1.0, 0.0, 0.0)).xyz));
        float face = smoothstep(0.35, 0.85, up);
        float n = cvN(vCovW.xz * 0.07) * 0.5 + cvN(vCovW.xz * 0.6 + 7.0) * 0.3 + cvN(vCovW.xz * 3.7 + 3.0) * 0.2;
        float snow = smoothstep(0.0, 0.22, uSnowD * 1.3 + n * 0.55 - 0.5) * face * step(0.001, uSnowD);
        float rime = ${rime ? "uRime * face * smoothstep(0.25, 0.75, n + uRime * 0.3) * 0.55" : "0.0"};
        diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.87, 0.89, 0.93), max(snow * 0.93, rime));
      }`);
  };
  mat.customProgramCacheKey = () => `${base}-cov${rime ? "r" : ""}`;
  return mat;
}
