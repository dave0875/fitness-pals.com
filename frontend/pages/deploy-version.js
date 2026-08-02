export async function getServerSideProps() {
  return {
    props: {
      releaseSha: process.env.NEXT_PUBLIC_RUNTRAINER_RELEASE_SHA || "unknown",
    },
  };
}

export default function DeployVersion({ releaseSha }) {
  return (
    <main>
      <h1>Fitness Pals release</h1>
      <p>
        Release: <code>{releaseSha}</code>
      </p>
    </main>
  );
}
