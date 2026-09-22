A = [5,2,6,1,9,5,3,6,9,6,3,3,7,8]
for j in range(1, len(A)):
        simpan = A[j]
        i = j-1
        while i >= 0  and A[i] > simpan:
                A[i+1] = A[i]
                i = i-1

        A[i + 1] = simpan
print (A)

