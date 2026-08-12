import uvicorn

if __name__ == '__main__':
    print("Starting BiliPods server on http://localhost:8000 ...")
    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=True)
