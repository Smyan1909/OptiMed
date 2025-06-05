import asyncio
from optimed.adapters.fhir_hapi.repository import HAPIFHIRRepository


async def main() -> None:
    async with HAPIFHIRRepository() as repo:
        patient = await repo.get_patient("example")

        # Option A – let Pydantic pre-serialize everything (recommended)
        print(patient.model_dump_json(indent=2))          # 👈 one-liner

        # Option B – keep json.dumps but teach it how to handle datetimes
        # print(json.dumps(patient.model_dump(mode="python"), indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())