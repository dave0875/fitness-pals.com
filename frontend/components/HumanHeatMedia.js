import media from "../config/human-heat-media.json";
import styles from "../styles/ElectricEntry.module.css";

function AthletePortrait({ asset, className, eager = false }) {
  const desktop = asset.variants.desktop;
  const mobile = asset.variants.mobile;

  return (
    <figure
      className={`${styles.athletePortrait} ${className}`}
      data-athlete-role={asset.role}
    >
      <picture>
        <source
          media="(max-width: 560px)"
          srcSet={mobile.src}
          type={`image/${mobile.format}`}
        />
        <img
          src={desktop.src}
          alt={asset.alt}
          width={desktop.width}
          height={desktop.height}
          loading={eager ? "eager" : "lazy"}
          decoding="async"
        />
      </picture>
    </figure>
  );
}

export default function HumanHeatMedia() {
  const woman = media.assets.find((asset) => asset.role === "adult woman athlete");
  const man = media.assets.find((asset) => asset.role === "adult man athlete");

  return (
    <div className={styles.athleteStage} data-contract={media.contractMarker}>
      <AthletePortrait asset={woman} className={styles.womanPortrait} eager />
      <AthletePortrait asset={man} className={styles.manPortrait} />

      <div
        className={styles.signalCard}
        aria-label="Illustrative readiness example, not authenticated athlete data"
      >
        <span>ILLUSTRATIVE READINESS</span>
        <strong>74</strong>
        <small>Demo only · not your athlete data.</small>
      </div>

      <div className={styles.motionLabel}>FORM / LOAD / RECOVERY</div>
      <p className={styles.mediaCredit}>
        Performance photography · Peter Zhan + Jakub Klucký / Unsplash
      </p>
    </div>
  );
}
