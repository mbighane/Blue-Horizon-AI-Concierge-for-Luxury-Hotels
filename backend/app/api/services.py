from fastapi import APIRouter

router = APIRouter()

@router.get("/service-example")
async def service_example():
    return {"message": "This is a service example endpoint."}