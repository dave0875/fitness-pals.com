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
    <div
      className={styles.athleteStage}
      data-contract={media.contractMarker}
      data-art-direction={media.artDirection.marker}
    >
      <AthletePortrait asset={woman} className={styles.womanPortrait} eager />
      <AthletePortrait asset={man} className={styles.manPortrait} />

      <div className={styles.presenceCard}>
        <span>YOU HAVE OUR ATTENTION</span>
        <strong>Built to notice. Ready to guide.</strong>
        <small>Performance intelligence shaped around your life, your ambition, and your next move.</small>
      </div>

      <div
        className={styles.signalCard}
        aria-label="Illustrative readiness example, not authenticated athlete data"
      >
        <span>ILLUSTRATIVE READINESS</span>
        <strong>74</strong>
        <small>Demo only · not your athlete data.</small>
      </div>

      <div className={styles.motionLabel}>FORM / AMBITION / ATTENTION</div>
      <p className={styles.mediaCredit}>
        Performance photography · Rodrigo Rodrigues + Praise Judah / Unsplash
      </p>
    </div>
  );
}
